"""HTTP client mapping + the Agno adapter (both offline; network stubbed)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap, export_yaml  # noqa: E402
from kiff_guard.adapters.agno import agno_hook  # noqa: E402


def _bound_map() -> ToolMap:
    return ToolMap().bind(
        "refund_order", action="REFUND_ORDER", entity_type="Order", entity_arg="order_id"
    )


def _client(capture):
    tm = ToolMap().bind("start_shift", action="START_SHIFT", entity_type="Shift", entity_arg="shift_id")
    c = HTTPClient(api_key="kiff_live_t_" + "y" * 32, tool_map=tm)

    def fake_post(path, body):
        capture["path"] = path
        capture["body"] = body
        return 200, {"proposal_id": "prop_1", "outcome": "allowed", "reasons": [], "message": ""}

    c._post = fake_post  # type: ignore[attr-defined]
    return c


def test_client_maps_tool_and_extracts_entity():
    cap = {}
    c = _client(cap)
    d = c.decide("t", "agent-a", "start_shift", {"shift_id": "s9", "opened_by": "bob"})
    assert d.outcome == "allowed" and d.proposal_id == "prop_1"
    assert cap["body"]["entity_id"] == "s9"
    assert cap["body"]["action_name"] == "START_SHIFT"
    assert cap["body"]["entity_type"] == "Shift"
    assert cap["body"]["actor_id"] == "agent-a"
    assert cap["body"]["parameters"] == {"opened_by": "bob"}
    assert "shift_id" not in cap["body"]["parameters"]


def test_client_never_sends_roles():
    cap = {}
    c = _client(cap)
    c.decide("t", "a", "start_shift", {"shift_id": "s1", "actor_roles": ["admin"]})
    assert "roles" not in cap["body"]


def test_client_unmapped_withholds_by_default():
    # An unbound tool never reaches KIFF, so enforce must not synthesize an
    # allow for it. Default is fail-safe.
    c = HTTPClient(api_key="kiff_live_t_" + "y" * 32, tool_map=ToolMap())
    d = c.decide("t", "a", "mystery", {"x": 1})
    assert d.outcome == "invalid" and d.withheld and "not bound" in d.reason


def test_client_unmapped_is_cleared_when_opted_in():
    c = HTTPClient(api_key="kiff_live_t_" + "y" * 32, tool_map=ToolMap(), unmapped="allow")
    d = c.decide("t", "a", "mystery", {"x": 1})
    assert d.outcome == "allowed" and "unmapped" in d.reason


def test_client_missing_entity_arg_is_invalid():
    tm = ToolMap().bind("start_shift", action="START_SHIFT", entity_type="Shift", entity_arg="shift_id")
    c = HTTPClient(api_key="kiff_live_t_" + "y" * 32, tool_map=tm)
    d = c.decide("t", "a", "start_shift", {"opened_by": "bob"})
    assert d.outcome == "invalid" and "shift_id" in d.reason


def test_agno_adapter_observe_runs_and_audits():
    # The adapter matches Agno's hook signature: hook(name, func, args).
    guard = Guard(mode="observe", agent="a")
    hook = agno_hook(guard)
    calls = []

    def refund_order(**kwargs):
        calls.append(kwargs)
        return "refunded"

    out = hook("refund_order", refund_order, {"order_id": "o1", "amount_cents": 42})
    assert out == "refunded"
    assert calls == [{"order_id": "o1", "amount_cents": 42}]
    assert guard.receipts[-1].state == "observed"
    assert guard.catalog.tools["refund_order"] == {"order_id", "amount_cents"}


def test_draft_export_yaml_from_catalog():
    guard = Guard(mode="observe", agent="a")
    hook = agno_hook(guard)
    hook("refund_order", lambda **k: None, {"order_id": "o1", "amount_cents": 1})
    yaml = export_yaml("acme", guard.catalog)
    assert "domain: acme" in yaml
    assert "name: refund_order" in yaml
    assert "TODO(human)" in yaml          # honesty boundary preserved
    assert "states: []" in yaml


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")


def test_client_refuses_allowed_on_non_success_status(monkeypatch):
    # KIFF puts the outcome in the body by design and uses status as a hint:
    # 400 for invalid, 429 for limit_exceeded, 502 for infra. Those are real
    # governance answers and must be honored from the body. But KIFF never
    # returns `allowed` on a non-2xx, so an `allowed` arriving with one did
    # not come from KIFF — a proxy, captive portal, or misdirected base_url.
    c = HTTPClient(api_key="kiff_live_t_" + "y" * 32, tool_map=_bound_map())
    monkeypatch.setattr(c, "_post", lambda path, body: (500, {"outcome": "allowed"}))

    d = c.decide("t", "a", "refund_order", {"order_id": "o1"})

    assert not d.allowed and d.withheld
    assert d.outcome == "invalid" and "non-success status" in d.reason


def test_client_honors_withheld_outcomes_on_non_success_status(monkeypatch):
    # The mirror of the above: a withheld outcome on a 4xx/5xx is exactly how
    # KIFF reports limit_exceeded and invalid, and must still be honored.
    c = HTTPClient(api_key="kiff_live_t_" + "y" * 32, tool_map=_bound_map())
    monkeypatch.setattr(c, "_post", lambda path, body: (429, {"outcome": "limit_exceeded"}))

    d = c.decide("t", "a", "refund_order", {"order_id": "o1"})

    assert d.outcome == "limit_exceeded" and d.withheld


def test_client_refuses_plaintext_base_url():
    # The API key rides every decide call, so http:// leaks a live credential
    # and lets anyone on the path rewrite the decision.
    with pytest.raises(ValueError, match="not https"):
        HTTPClient(api_key="kiff_live_t_" + "y" * 32, tool_map=ToolMap(), base_url="http://api.kiff.dev")


def test_client_allows_plaintext_loopback_and_explicit_opt_in():
    key = "kiff_live_t_" + "y" * 32
    # Loopback is the normal local-development and test-double shape.
    HTTPClient(api_key=key, tool_map=ToolMap(), base_url="http://127.0.0.1:8931")
    HTTPClient(api_key=key, tool_map=ToolMap(), base_url="http://localhost:8931")
    # And an explicit opt-in for an out-of-band secure channel.
    HTTPClient(api_key=key, tool_map=ToolMap(), base_url="http://kiff.internal", allow_insecure_http=True)
