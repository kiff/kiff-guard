"""Haystack adapter — ConfirmationStrategy (vote shape)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Decision, Guard  # noqa: E402
from kiff_guard.adapters.haystack import kiff_confirmation_strategy  # noqa: E402


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


class _Dec:
    """Stand-in for haystack ToolExecutionDecision."""

    def __init__(self, tool_name, tool_call_id, execute, feedback=""):
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self.execute = execute
        self.feedback = feedback


def _strategy(guard, **kw):
    return kiff_confirmation_strategy(
        guard, decision_factory=lambda name, tcid, execute, feedback="": _Dec(name, tcid, execute, feedback), **kw
    )


def _run(strategy, tool, args):
    return strategy.run(tool_name=tool, tool_description="", tool_params=args, tool_call_id="tc")


def test_observe_always_executes_and_records_observed():
    guard = Guard(mode="observe", agent="hay")
    out = _run(_strategy(guard), "send_email", {"to": "x", "body": "y"})
    assert out.execute is True  # observe always allows
    assert guard.receipts[-1].state == "observed"
    assert guard.catalog.tools["send_email"] == {"to", "body"}


def test_enforce_allowed_executes_and_records_one_receipt():
    stub = _StubClient(outcome="allowed")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="hay")
    out = _run(_strategy(guard), "read_file", {"path": "x"})
    assert out.execute is True
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is True


def test_enforce_withheld_does_not_execute_and_records_one_receipt():
    stub = _StubClient(outcome="blocked", reason="blocked by policy")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="hay")
    out = _run(_strategy(guard), "delete_account", {"account_id": "a9"})
    assert out.execute is False
    assert "withheld" in out.feedback
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is False


def test_enforce_fail_closed_on_client_error():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="hay")
    out = _run(_strategy(guard, fail_closed=True), "terminal", {"cmd": "ls"})
    assert out.execute is False and "fail-closed" in out.feedback


def test_enforce_fail_open_when_configured():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="hay")
    out = _run(_strategy(guard, fail_closed=False), "terminal", {"cmd": "ls"})
    assert out.execute is True  # fail open -> tool proceeds


def test_unknown_outcome_fails_safe():
    stub = _StubClient(outcome="quarantined", reason="unknown future outcome")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="hay")
    out = _run(_strategy(guard), "delete_account", {"account_id": "a9"})
    assert out.execute is False
    assert len(guard.receipts) == 1 and guard.receipts[-1].executed is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
