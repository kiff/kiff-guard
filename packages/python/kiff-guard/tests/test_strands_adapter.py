"""Strands adapter — BeforeToolCallEvent hook (vote shape)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Decision, Guard  # noqa: E402
from kiff_guard.adapters.strands import kiff_before_tool_call  # noqa: E402


class _StubClient:
    def __init__(self, outcome="allowed", reason="", proposal_id="prop_1", raises=False):
        self._d = Decision(outcome=outcome, reason=reason, proposal_id=proposal_id)
        self._raises = raises
        self.calls = 0

    def decide(self, tenant, agent, tool, args):
        self.calls += 1
        if self._raises:
            raise RuntimeError("transport down")
        return self._d


class _Event:
    def __init__(self, name, args):
        self.tool_use = {"name": name, "input": args, "toolUseId": "tu"}
        self.cancel_tool = False


def test_observe_never_cancels_and_records_observed():
    guard = Guard(mode="observe", agent="strands")
    cb = kiff_before_tool_call(guard)
    ev = _Event("delete_account", {"account_id": "a9"})
    cb(ev)
    assert ev.cancel_tool is False  # observe never cancels
    assert guard.receipts[-1].state == "observed"
    assert guard.catalog.tools["delete_account"] == {"account_id"}


def test_enforce_allowed_leaves_event_and_records_one_receipt():
    stub = _StubClient(outcome="allowed")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="strands")
    cb = kiff_before_tool_call(guard)
    ev = _Event("read_file", {"path": "x"})
    cb(ev)
    assert ev.cancel_tool is False  # allowed -> Strands runs the tool
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is True


def test_enforce_withheld_sets_cancel_and_records_one_receipt():
    stub = _StubClient(outcome="blocked", reason="blocked by policy")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="strands")
    cb = kiff_before_tool_call(guard)
    ev = _Event("delete_account", {"account_id": "a9"})
    cb(ev)
    assert isinstance(ev.cancel_tool, str) and "withheld" in ev.cancel_tool
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is False


def test_enforce_fail_closed_on_client_error():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="strands")
    cb = kiff_before_tool_call(guard, fail_closed=True)
    ev = _Event("terminal", {"cmd": "ls"})
    cb(ev)
    assert isinstance(ev.cancel_tool, str) and "fail-closed" in ev.cancel_tool


def test_enforce_fail_open_when_configured():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="strands")
    cb = kiff_before_tool_call(guard, fail_closed=False)
    ev = _Event("terminal", {"cmd": "ls"})
    cb(ev)
    assert ev.cancel_tool is False  # fail open -> tool proceeds


def test_unknown_outcome_fails_safe():
    stub = _StubClient(outcome="quarantined", reason="unknown future outcome")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="strands")
    cb = kiff_before_tool_call(guard)
    ev = _Event("delete_account", {"account_id": "a9"})
    cb(ev)
    assert isinstance(ev.cancel_tool, str)  # withheld
    assert len(guard.receipts) == 1 and guard.receipts[-1].executed is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
