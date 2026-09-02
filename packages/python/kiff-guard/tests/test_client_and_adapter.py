"""HTTP client mapping + the Agno adapter (both offline; network stubbed)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap, export_yaml  # noqa: E402
from kiff_guard.adapters.agno import agno_hook  # noqa: E402


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
