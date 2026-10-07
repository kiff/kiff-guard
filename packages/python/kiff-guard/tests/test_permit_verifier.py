"""The KIFF execution-permit verifier (RFC 046 D4, D5): every refusal case,
at-most-once execution, read-only recovery, key trust, and interop with the
permits KIFF's own (Go) issuer mints."""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import time

import pytest

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from kiff_guard.permit import (  # noqa: E402
    Adapter,
    JWKSKeys,
    KeyUnavailable,
    Outcome,
    PinnedKey,
    PinnedKeys,
    SQLiteStore,
    Verifier,
    args_sha256,
    canonicalize,
)
from kiff_guard.permit.relay import Relay, RelayTool  # noqa: E402
from kiff_guard.permit.stripe import StripeRefunds  # noqa: E402

HERE = os.path.dirname(__file__)
ISS, AUD, TENANT, TOOL = "https://api.kiff.dev", "https://refunds.example.com/mcp", "t1", "refund_order"
ARGS = {"order_number": "1042", "amount_eur": 80, "idempotency_key": "op-1"}


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Signer:
    def __init__(self, kid: str = "k1") -> None:
        self.kid = kid
        self.priv = Ed25519PrivateKey.generate()
        self.pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def mint(self, now: float, *, op: str = "op-1", args=None, life: int = 60, header=None, **over) -> str:
        args = ARGS if args is None else args
        h = {"alg": "Ed25519", "typ": "kiff-permit+jwt", "kid": self.kid}
        h.update(header or {})
        detail = {"type": "https://kiff.dev/permits/tool-call", "tenant": TENANT, "tool": TOOL,
                  "args_sha256": args_sha256(args), "op": op, "card": "card-1", "decision": op}
        detail.update(over.pop("detail", {}))
        c = {"iss": ISS, "aud": AUD, "sub": "agent-1", "iat": int(now), "exp": int(now) + life, "jti": "pmt_x",
             "authorization_details": [detail]}
        c.update(over)
        signing = b64(json.dumps(h).encode()) + "." + b64(json.dumps(c).encode())
        return signing + "." + b64(self.priv.sign(signing.encode()))


class FakeRefunds(Adapter):
    """A downstream service that records executions and answers lookups."""

    def __init__(self, delay: float = 0, answer: str = "succeeded") -> None:
        self.executed = []
        self.refunds = {}
        self.delay, self.answer = delay, answer
        self.lock = threading.Lock()

    def execute(self, op, arguments):
        if self.delay:
            time.sleep(self.delay)
        with self.lock:
            self.executed.append(op)
            if self.answer == "succeeded":
                self.refunds[op] = {"id": "re_" + op}
        if self.answer == "raise":
            raise ConnectionError("lost")
        return Outcome(self.answer, self.refunds.get(op))

    def lookup(self, op, arguments):
        r = self.refunds.get(op)
        return Outcome("succeeded", r) if r else None


@pytest.fixture
def rig(tmp_path):
    clock, signer = Clock(), Signer()
    keys = PinnedKeys([PinnedKey("k1", signer.pub, clock.t + 86400)], clock=clock)
    store = SQLiteStore(str(tmp_path / "ops.db"))
    v = Verifier(issuer=ISS, audience=AUD, tenant=TENANT, keys=keys, store=store, clock=clock)
    return v, signer, clock, store


# -- canonical JSON ----------------------------------------------------------

def test_jcs_vectors_shared_with_kiff():
    for v in json.load(open(os.path.join(HERE, "testdata", "jcs_vectors.json"), encoding="utf-8")):
        assert canonicalize(json.loads(v["input"])).decode() == v["canonical"], v["name"]


def test_a_permit_kiff_minted_verifies(tmp_path):
    fx = json.load(open(os.path.join(HERE, "testdata", "go_permit_fixture.json")))
    keys = JWKSKeys(fetch=lambda url: fx["jwks"], clock=lambda: fx["now"])
    v = Verifier(issuer=fx["issuer"], audience=fx["audience"], tenant=fx["tenant"], keys=keys,
                 store=SQLiteStore(str(tmp_path / "ops.db")), clock=lambda: fx["now"])
    assert args_sha256(fx["arguments"]) == fx["args_sha256"]
    d = v.authenticate(fx["token"], fx["tool"], fx["arguments"])
    assert d["op"] == "op-fixture" and d["card"] == "card-fixture" and d["sub"] == "agent-fixture"


# -- at most once ------------------------------------------------------------

def test_allowed_call_runs_once_and_a_retry_gets_the_result(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    tok = s.mint(clock.t)
    first = v.run(tok, TOOL, ARGS, tool)
    assert first.state == "succeeded" and tool.executed == ["op-1"]
    again = v.run(tok, TOOL, dict(reversed(list(ARGS.items()))), tool)
    assert again.state == "succeeded" and again.result == {"id": "re_op-1"} and tool.executed == ["op-1"]


def test_concurrent_presentations_execute_once(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds(delay=0.2)
    tok = s.mint(clock.t)
    results = []
    threads = [threading.Thread(target=lambda: results.append(v.run(tok, TOOL, ARGS, tool))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert tool.executed == ["op-1"]
    assert sorted({r.state for r in results}) == ["in_progress", "succeeded"]


def test_expired_permit_still_retrieves_a_recorded_outcome(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    tok = s.mint(clock.t)
    v.run(tok, TOOL, ARGS, tool)
    clock.t += 3600
    assert v.run(tok, TOOL, ARGS, tool).state == "succeeded" and tool.executed == ["op-1"]


def test_expired_permit_never_starts_a_new_execution(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    tok = s.mint(clock.t)
    clock.t += 60 + 31  # lifetime plus the 30 s tolerance, plus one
    out = v.run(tok, TOOL, ARGS, tool)
    assert out.state == "refused" and out.reason == "expired" and tool.executed == []


def test_acceptance_window_is_lifetime_plus_tolerance(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    tok = s.mint(clock.t)
    clock.t += 90
    assert v.run(tok, TOOL, ARGS, tool).state == "succeeded"


def test_permit_that_expires_before_the_send_is_not_sent(rig, tmp_path):
    v, s, clock, store = rig
    tool = FakeRefunds()
    tok = s.mint(clock.t)
    real_claim = store.claim

    def slow_claim(*a, **k):
        ok = real_claim(*a, **k)
        clock.t += 200  # the process stalls between claiming and sending
        return ok

    store.claim = slow_claim
    out = v.run(tok, TOOL, ARGS, tool)
    assert out.state == "not_sent" and tool.executed == []
    store.claim = real_claim
    assert v.run(tok, TOOL, ARGS, tool).state == "not_sent"  # final: never sent later


# RFC 046 "Done when": crash before send, then expiry or revocation.
def test_crash_before_send_ends_unknown_and_never_sends(rig):
    v, s, clock, store = rig
    tool = FakeRefunds()
    store.claim("op-1", TOOL, args_sha256(ARGS), ARGS, "dead-process", clock.t, 120)  # then the process died
    clock.t += 121
    swept = v.sweep({TOOL: tool})
    assert [o.state for o in swept] == ["unknown"] and tool.executed == []
    # Even a live permit for the op does not resend it.
    out = v.run(s.mint(clock.t), TOOL, ARGS, tool)
    assert out.state == "unknown" and tool.executed == []
    assert [r.op for r in v.unknown()] == ["op-1"]


# RFC 046 "Done when": crash after send.
def test_crash_after_send_is_recovered_by_lookup(rig):
    v, s, clock, store = rig
    tool = FakeRefunds()
    store.claim("op-1", TOOL, args_sha256(ARGS), ARGS, "dead-process", clock.t, 120)
    tool.refunds["op-1"] = {"id": "re_op-1"}  # Stripe refunded, then the process died
    clock.t += 121
    assert [o.state for o in v.sweep({TOOL: tool})] == ["succeeded"]
    assert v.run(s.mint(clock.t - 3600), TOOL, ARGS, tool).result == {"id": "re_op-1"}
    assert tool.executed == []


def test_lost_answer_is_unknown_and_never_resent(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds(answer="raise")
    tok = s.mint(clock.t)
    assert v.run(tok, TOOL, ARGS, tool).state == "unknown"
    assert v.run(tok, TOOL, ARGS, tool).state == "unknown"
    assert tool.executed == ["op-1"]


def test_recorded_op_with_other_arguments_is_refused(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    v.run(s.mint(clock.t), TOOL, ARGS, tool)
    other = dict(ARGS, amount_eur=900)
    out = v.run(s.mint(clock.t, args=other), TOOL, other, tool)
    assert out.state == "refused" and out.reason == "op_mismatch" and tool.executed == ["op-1"]


def test_local_policy_refuses_before_anything_runs(tmp_path):
    clock, s = Clock(), Signer()
    v = Verifier(issuer=ISS, audience=AUD, tenant=TENANT, store=SQLiteStore(str(tmp_path / "o.db")), clock=clock,
                 keys=PinnedKeys([PinnedKey("k1", s.pub, clock.t + 60)], clock=clock),
                 policy=lambda tool, a: "refunds above 50 need a person" if a["amount_eur"] > 50 else None)
    tool = FakeRefunds()
    out = v.run(s.mint(clock.t), TOOL, ARGS, tool)
    assert out.state == "refused" and out.reason == "local_policy" and tool.executed == []


# -- every refusal -------------------------------------------------------------

@pytest.mark.parametrize("case,code", [
    ({"header": {"typ": "JWT"}}, "wrong_type"),
    ({"header": {"alg": "EdDSA"}}, "wrong_alg"),
    ({"header": {"kid": "k9"}}, "unknown_key"),
    ({"iss": "https://evil.example"}, "wrong_issuer"),
    ({"aud": "https://other.example/mcp"}, "wrong_audience"),
    ({"detail": {"tenant": "t2"}}, "wrong_tenant"),
    ({"detail": {"tool": "delete_account"}}, "wrong_tool"),
    ({"detail": {"args_sha256": "0" * 64}}, "args_mismatch"),
    ({"detail": {"type": "urn:other"}}, "malformed"),
    ({"life": 3600}, "lifetime_too_long"),
])
def test_refusals(rig, case, code):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    out = v.run(s.mint(clock.t, **case), TOOL, ARGS, tool)
    assert out.state == "refused" and out.reason == code and tool.executed == []


def test_changed_arguments_and_tampering_are_refused(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    tok = s.mint(clock.t)
    assert v.run(tok, TOOL, dict(ARGS, amount_eur=8000), tool).reason == "args_mismatch"
    h, p, sig = tok.split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=="))
    claims["aud"] = AUD
    claims["authorization_details"][0]["tenant"] = TENANT
    claims["exp"] += 3600
    forged = h + "." + b64(json.dumps(claims).encode()) + "." + sig
    assert v.run(forged, TOOL, ARGS, tool).reason == "bad_signature"
    other = Signer("k1")  # right kid, wrong key
    assert v.run(other.mint(clock.t), TOOL, ARGS, tool).reason == "bad_signature"
    assert v.run("not.a.permit", TOOL, ARGS, tool).reason == "malformed"
    assert tool.executed == []


def test_issued_in_the_future_is_refused(rig):
    v, s, clock, _ = rig
    out = v.run(s.mint(clock.t + 120), TOOL, ARGS, FakeRefunds())
    assert out.reason == "issued_in_future"


def test_lifetime_bound_is_configurable_but_capped():
    with pytest.raises(ValueError):
        Verifier(issuer=ISS, audience=AUD, tenant=TENANT, keys=None, store=None, max_lifetime=301)


# -- key trust -----------------------------------------------------------------

def jwks(*signers):
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": b64(s.pub), "kid": s.kid, "alg": "Ed25519"} for s in signers]}


def test_removed_key_is_no_longer_trusted_after_refresh():
    clock, a, b = Clock(), Signer("a"), Signer("b")
    doc = {"v": jwks(a, b)}
    keys = JWKSKeys(fetch=lambda url: doc["v"], clock=clock)
    assert keys.key("a") == a.pub
    doc["v"] = jwks(b)  # KIFF removed a compromised key
    clock.t += 299
    assert keys.key("a") == a.pub  # within the refresh bound
    clock.t += 2
    assert keys.key("a") is None and keys.key("b") == b.pub


def test_unknown_kid_refetches_at_most_once_a_minute():
    clock, a, b = Clock(), Signer("a"), Signer("b")
    calls = []
    doc = {"v": jwks(a)}
    keys = JWKSKeys(fetch=lambda url: calls.append(1) or doc["v"], clock=clock)
    keys.key("a")
    doc["v"] = jwks(a, b)
    clock.t += 10
    assert keys.key("b") is None and len(calls) == 1
    clock.t += 51
    assert keys.key("b") == b.pub and len(calls) == 2


def test_stale_key_set_fails_closed_after_an_hour():
    clock, a = Clock(), Signer("a")
    state = {"up": True}

    def fetch(url):
        if not state["up"]:
            raise OSError("down")
        return jwks(a)

    keys = JWKSKeys(fetch=fetch, clock=clock)
    assert keys.key("a") == a.pub
    state["up"] = False
    clock.t += 3599
    assert keys.key("a") == a.pub
    clock.t += 2
    with pytest.raises(KeyUnavailable):
        keys.key("a")


def test_distrust_list_wins_and_pins_expire():
    clock, a = Clock(), Signer("a")
    assert JWKSKeys(fetch=lambda u: jwks(a), distrust=["a"], clock=clock).key("a") is None
    pinned = PinnedKeys([PinnedKey("a", b64(a.pub), clock.t + 10)], clock=clock)
    assert pinned.key("a") == a.pub
    clock.t += 11
    assert pinned.key("a") is None
    assert PinnedKeys([PinnedKey("a", a.pub, clock.t + 99)], distrust=["a"], clock=clock).key("a") is None


def test_trust_bounds_cannot_be_loosened():
    with pytest.raises(ValueError):
        JWKSKeys(refresh=600)
    with pytest.raises(ValueError):
        JWKSKeys(stale_limit=7200)


# -- the Stripe adapter --------------------------------------------------------

class FakeStripe:
    def __init__(self):
        self.requests, self.refunds = [], []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if req.get_method() == "POST":
            params = dict(p.split("=", 1) for p in req.data.decode().split("&"))
            r = {"id": "re_%d" % len(self.refunds), "amount": int(params["amount"]), "currency": "eur",
                 "status": "succeeded", "payment_intent": params["payment_intent"],
                 "metadata": {"kiff_op": params["metadata%5Bkiff_op%5D"]}}
            self.refunds.append(r)
            body = r
        else:
            body = {"data": self.refunds}
        return io.BytesIO(json.dumps(body).encode())


def test_stripe_adapter_uses_the_op_as_key_and_metadata():
    fake = FakeStripe()
    a = StripeRefunds("sk_test_x", lambda args: {"payment_intent": "pi_1", "amount": args["amount_eur"] * 100}, opener=fake)
    out = a.execute("op-1", ARGS)
    assert out.state == "succeeded" and out.result["amount"] == 8000
    post = fake.requests[0]
    assert post.get_header("Idempotency-key") == "op-1"
    assert "metadata%5Bkiff_op%5D=op-1" in post.data.decode()
    assert a.lookup("op-1", ARGS).result["id"] == "re_0"
    assert a.lookup("op-2", ARGS) is None


# -- the relay -----------------------------------------------------------------

def relay_call(app, body, token="Bearer relay-secret", permit=""):
    raw = json.dumps(body).encode()
    env = {"REQUEST_METHOD": "POST", "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
           "HTTP_AUTHORIZATION": token, "HTTP_KIFF_PERMIT": permit}
    status = {}
    out = b"".join(app(env, lambda s, h: status.setdefault("s", s)))
    return status["s"], json.loads(out) if out and status["s"].startswith("200") else out


def test_relay_runs_only_listed_tools_with_a_permit(rig):
    v, s, clock, _ = rig
    tool = FakeRefunds()
    app = Relay(v, {TOOL: RelayTool(tool, {"type": "object"}, "Refund an order")}, transport_token="relay-secret")
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": TOOL, "arguments": ARGS}}
    assert relay_call(app, call, token="Bearer wrong")[0].startswith("401")
    _, no_permit = relay_call(app, call)
    assert no_permit["result"]["isError"] and tool.executed == []
    _, ok = relay_call(app, call, permit=s.mint(clock.t))
    assert not ok["result"]["isError"] and tool.executed == ["op-1"]
    _, unknown = relay_call(app, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "transfer_funds", "arguments": {}}})
    assert unknown["error"]["code"] == -32602
    _, listed = relay_call(app, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert [t["name"] for t in listed["result"]["tools"]] == [TOOL]
