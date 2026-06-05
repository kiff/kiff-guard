"""LlamaIndex adapter — AgentWorkflow.call_tool override (middleware, async).

Drives the SDK-independent core (``run_guard_tool_call``) directly, so these
tests run without ``llama-index-core`` installed. ``llama_index.py`` wires
this same core into a ``GuardedAgentWorkflow`` subclass; the gate logic under
test is identical.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Decision, Guard, Hold  # noqa: E402
from kiff_guard.adapters.llama_index_core import run_guard_tool_call  # noqa: E402


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


def _drive(guard, tool, args, *, fail_closed=True):
    """Run the async core with a continuation that records whether it ran.
    Returns (ran, raised_hold)."""
    ran = {"v": False}

    async def run_tool():
        ran["v"] = True
        return "ok"

    async def _go():
        return await run_guard_tool_call(guard, tool, args, run_tool, fail_closed=fail_closed)

    try:
        asyncio.run(_go())
    except Hold:
        return ran["v"], True
    return ran["v"], False


def test_observe_runs_tool_and_records_observed():
    guard = Guard(mode="observe", agent="llama-index")
    ran, held = _drive(guard, "delete_account", {"account_id": "a9"})
    assert ran is True and held is False
    assert guard.receipts[-1].state == "observed"
    assert guard.catalog.tools["delete_account"] == {"account_id"}


def test_enforce_allowed_runs_tool_and_records_one_receipt():
    stub = _StubClient(outcome="allowed")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="llama-index")
    ran, held = _drive(guard, "read_file", {"path": "x"})
    assert ran is True and held is False
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is True


def test_enforce_withheld_raises_hold_and_records_one_receipt():
    stub = _StubClient(outcome="blocked", reason="blocked by policy")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="llama-index")
    ran, held = _drive(guard, "delete_account", {"account_id": "a9"})
    assert ran is False and held is True  # tool never ran; Hold raised
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is False


def test_enforce_fail_closed_on_client_error_raises_hold():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="llama-index")
    ran, held = _drive(guard, "terminal", {"cmd": "ls"}, fail_closed=True)
    assert ran is False and held is True  # fail-closed -> tool blocked


def test_enforce_fail_open_when_configured_runs_tool():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="llama-index")
    ran, held = _drive(guard, "terminal", {"cmd": "ls"}, fail_closed=False)
    assert ran is True and held is False  # fail-open -> tool proceeds


def test_unknown_outcome_fails_safe():
    stub = _StubClient(outcome="quarantined", reason="unknown future outcome")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="llama-index")
    ran, held = _drive(guard, "delete_account", {"account_id": "a9"})
    assert ran is False and held is True  # unknown outcome withholds
    assert len(guard.receipts) == 1 and guard.receipts[-1].executed is False


def test_enforce_allowed_records_exactly_one_receipt_not_two():
    stub = _StubClient(outcome="allowed")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="llama-index")
    _drive(guard, "read_file", {"path": "x"})
    # decide_only must not record; only record_executed does -> exactly one.
    assert len(guard.receipts) == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
