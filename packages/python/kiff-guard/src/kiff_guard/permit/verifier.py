"""Verifying a KIFF execution permit and running the call at most once
(RFC 046 D5).

Use it inside the tool (``verify`` mode) or in a relay that adds the
downstream key (``relay`` mode)::

    verifier = Verifier(issuer="https://api.kiff.dev",
                        audience="https://refunds.example.com/mcp",
                        tenant="<your KIFF account id>",
                        keys=JWKSKeys(),
                        store=SQLiteStore("/var/lib/refunds/permits.db"))
    outcome = verifier.run(request.headers["KIFF-Permit"], "refund_order", arguments, adapter)

The check, in order:

1. Authenticity, always: ``typ``, ``alg: Ed25519``, a trusted ``kid`` and a
   valid signature; the issuer, this tool's audience, exactly one
   ``authorization_details`` entry of KIFF's type naming this account; the
   tool being called; ``args_sha256`` equal to the hash of the arguments
   received; a lifetime of at most ``max_lifetime`` (60 s by default, never
   above 300); ``iat`` not more than 30 s in the future.
2. The operation (``op``), in a durable store:

   - already recorded: no new execution, whatever the permit's ``exp``. The
     stored outcome is returned, or "in progress", or a read-only
     ``lookup`` is run to settle it.
   - not recorded: a new execution, which needs an unexpired permit (``exp``
     plus 30 s of tolerance: 90 s after minting by default). The verifier
     claims the op, checks the permit is still unexpired immediately before
     it sends, and records the outcome.

Recovery never sends. A row whose process died mid-call, or whose downstream
answer was lost, is settled only by the adapter's ``lookup``; what that
cannot settle is ``unknown`` and goes to a person. So a request that can
take effect is sent once per op, by the verifier that claimed it, and only
under an unexpired permit.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

from .jcs import args_sha256
from .keys import KeyUnavailable
from .store import FINAL_STATES, Row
from .token import DETAIL_TYPE, PermitError, decode_and_verify

__all__ = ["Verifier", "Outcome", "Adapter", "PermitError"]


class Outcome:
    """How a call ended, as the verifier reports it.

    ``state`` is one of ``succeeded``, ``failed`` (the downstream service
    answered with a refusal), ``not_sent`` (the verifier did not send it),
    ``unknown`` (it may have run; a person must check), ``in_progress``
    (another attempt holds it; retry later) or ``refused`` (the permit does
    not authorize it; ``reason`` is the PermitError code).
    """

    def __init__(self, state: str, result: Any = None, reason: str = "", message: str = "") -> None:
        self.state, self.result, self.reason, self.message = state, result, reason, message

    @property
    def ran(self) -> bool:
        return self.state == "succeeded"

    def __repr__(self) -> str:
        return "Outcome(%r, reason=%r)" % (self.state, self.reason)


class Adapter:
    """How one downstream call is made and recovered. Subclass it.

    ``execute`` makes the call once and classifies the answer: return
    ``Outcome("succeeded", result)``, ``Outcome("failed", result)`` for a
    final refusal from the service, or ``Outcome("unknown")`` when the
    answer did not say what happened (timeout, lost connection, 5xx). It
    receives the operation id to use as the service's idempotency key.

    ``lookup`` is read-only: find the call's result by a reference the
    original request carried, and return it, or None when nothing is found
    (which does not prove the call did not run). A money-moving adapter must
    implement it.
    """

    #: Calls that move money or change accounts must be recoverable.
    moves_money = True

    def execute(self, op: str, arguments: Dict[str, Any]) -> Outcome:  # pragma: no cover - interface
        raise NotImplementedError

    def lookup(self, op: str, arguments: Dict[str, Any]) -> Optional[Outcome]:
        return None


class Verifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        tenant: str,
        keys,
        store,
        max_lifetime: float = 60,
        skew: float = 30,
        lease: float = 120,
        policy: Optional[Callable[[str, Dict[str, Any]], Optional[str]]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not (0 < max_lifetime <= 300):
            raise ValueError("max_lifetime must be between 0 and 300 seconds (RFC 046 D5)")
        if not issuer or not audience or not tenant:
            raise ValueError("issuer, audience and tenant are required")
        self.issuer, self.audience, self.tenant = issuer, audience, tenant
        self.keys, self.store = keys, store
        self.max_lifetime, self.skew, self.lease = max_lifetime, skew, lease
        self.policy = policy
        self._clock = clock
        self._owner = "v-" + uuid.uuid4().hex[:12]

    # -- stage 1 -----------------------------------------------------------

    def authenticate(self, token: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Check the permit is KIFF's, for exactly this call. Returns the
        tool-call detail (``op``, ``card``, ...) plus ``exp``. Raises
        PermitError; KeyUnavailable when no key set can be trusted."""
        _, c = decode_and_verify(token, self.keys.key)
        if c.get("iss") != self.issuer:
            raise PermitError("wrong_issuer", "the permit was not issued by the configured issuer")
        if c.get("aud") != self.audience:
            raise PermitError("wrong_audience", "the permit is for another tool or relay (aud)")
        details = c.get("authorization_details")
        if not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], dict):
            raise PermitError("malformed", "the permit must carry exactly one authorization_details entry")
        d = details[0]
        if d.get("type") != DETAIL_TYPE:
            raise PermitError("malformed", "the permit's authorization_details type is not KIFF's tool-call")
        if d.get("tenant") != self.tenant:
            raise PermitError("wrong_tenant", "the permit is for another KIFF account")
        if d.get("tool") != tool:
            raise PermitError("wrong_tool", "the permit is for another tool")
        if d.get("args_sha256") != args_sha256(arguments):
            raise PermitError("args_mismatch", "the arguments received are not the ones KIFF authorized")
        op = d.get("op")
        if not isinstance(op, str) or not op:
            raise PermitError("malformed", "the permit names no operation")
        iat, exp = c.get("iat"), c.get("exp")
        if not isinstance(iat, (int, float)) or not isinstance(exp, (int, float)) or isinstance(iat, bool) or isinstance(exp, bool):
            raise PermitError("malformed", "the permit needs numeric iat and exp")
        if exp - iat > self.max_lifetime:
            raise PermitError("lifetime_too_long", "the permit's lifetime is longer than this verifier accepts")
        if iat > self._clock() + self.skew:
            raise PermitError("issued_in_future", "the permit is issued in the future; check the clock")
        out = dict(d)
        out["exp"], out["sub"], out["jti"] = exp, c.get("sub"), c.get("jti")
        return out

    def _live(self, exp: float) -> bool:
        return self._clock() <= exp + self.skew

    # -- stage 2 -----------------------------------------------------------

    def run(self, token: str, tool: str, arguments: Dict[str, Any], adapter: Adapter) -> Outcome:
        """Verify the permit and run the call at most once. Never raises for
        a refused permit: the Outcome says so."""
        try:
            d = self.authenticate(token, tool, arguments)
        except PermitError as e:
            return Outcome("refused", reason=e.code, message=str(e))
        except KeyUnavailable as e:
            return Outcome("refused", reason="keys_unavailable", message=str(e))
        op, h = d["op"], d["args_sha256"]

        row = self.store.get(op)
        if row is not None:
            return self._recorded(row, h, adapter)

        if not self._live(d["exp"]):
            return Outcome("refused", reason="expired", message="the permit has expired; nothing was sent")
        if self.policy is not None:
            why = self.policy(tool, arguments)
            if why:
                return Outcome("refused", reason="local_policy", message=why)
        now = self._clock()
        if not self.store.claim(op, tool, h, arguments, self._owner, now, self.lease):
            row = self.store.get(op)
            return self._recorded(row, h, adapter) if row else Outcome("in_progress")
        # Checked again immediately before sending, not only when claimed.
        if not self._live(d["exp"]):
            self.store.finish(op, self._owner, "not_sent", None, "expired_before_send", self._clock())
            return Outcome("not_sent", reason="expired_before_send", message="the permit expired before the call was sent")
        try:
            out = adapter.execute(op, arguments)
        except Exception as e:  # the adapter could not say what happened
            out = Outcome("unknown", reason="adapter_error", message=type(e).__name__)
        if out.state not in ("succeeded", "failed", "unknown"):
            out = Outcome("unknown", reason="adapter_returned_" + out.state)
        self.store.finish(op, self._owner, out.state, out.result, out.reason, self._clock())
        return out

    def _recorded(self, row: Row, h: str, adapter: Adapter) -> Outcome:
        if row.args_sha256 != h:
            return Outcome("refused", reason="op_mismatch", message="this operation was recorded with other arguments")
        if row.state in FINAL_STATES:
            return Outcome(row.state, row.result, row.reason)
        now = self._clock()
        if row.state == "started" and row.lease_until > now:
            return Outcome("in_progress", message="another attempt is running this operation; retry later")
        return self._settle(row, adapter)

    def _settle(self, row: Row, adapter: Adapter) -> Outcome:
        """Read-only recovery: lookup, never a resend."""
        now = self._clock()
        if not self.store.take_expired_lease(row.op, self._owner, now, self.lease):
            return Outcome("in_progress", message="another attempt is settling this operation; retry later")
        try:
            found = adapter.lookup(row.op, row.arguments)
        except Exception:
            found = None
        if found is not None and found.state in ("succeeded", "failed"):
            self.store.finish(row.op, self._owner, found.state, found.result, "recovered_by_lookup", self._clock())
            return Outcome(found.state, found.result, "recovered_by_lookup")
        self.store.finish(row.op, self._owner, "unknown", None, "unsettled", self._clock())
        return Outcome("unknown", reason="unsettled",
                       message="this call may have run; KIFF and this tool will not send it again. Check the downstream service.")

    def sweep(self, adapters: Dict[str, Adapter]) -> List[Outcome]:
        """Settle every started row whose lease has expired (a process died
        mid-call) with its tool's lookup. Run it on start-up and
        periodically: a call whose response was lost is never presented
        again by KIFF, so only the sweep settles it."""
        out = []
        for row in self.store.expired(self._clock()):
            adapter = adapters.get(row.tool)
            if adapter is None:
                continue
            out.append(self._settle(row, adapter))
        return out

    def unknown(self) -> Iterable[Row]:
        """Operations whose outcome a person must check."""
        return self.store.unknown()
