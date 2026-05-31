"""Microsoft Agent Framework adapter — FunctionMiddleware core
(vote shape, async). Tests the SDK-independent core directly."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Decision, Guard  # noqa: E402
from kiff_guard.adapters.microsoft_agent_framework_core import (  # noqa: E402
    args_to_dict,
    run_guard_middleware,
)


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


class _Fn:
    def __init__(self, name):
        self.name = name


class _Ctx:
    """Duck-typed FunctionInvocationContext."""

    def __init__(self, name, arguments):
        self.function = _Fn(name)
        self.arguments = arguments
        self.result = None


def _drive(guard, name, args, fail_closed=True):
    """Run the middleware core once; return (ran, ctx)."""
    ran = {"v": False}

    async def call_next():
        ran["v"] = True

    ctx = _Ctx(name, args)
    asyncio.run(run_guard_middleware(guard, ctx, call_next, fail_closed=fail_closed))
    return ran["v"], ctx


def test_args_to_dict_handles_mapping_and_basemodel_like():
    assert args_to_dict({"a": 1}) == {"a": 1}
    assert args_to_dict(None) == {}

    class _Model:
        def model_dump(self):
            return {"x": 2}

    assert args_to_dict(_Model()) == {"x": 2}


def test_observe_runs_tool_and_records_observed():
    guard = Guard(mode="observe", agent="maf")
    ran, ctx = _drive(guard, "send_email", {"to": "x", "body": "y"})
    assert ran is True  # observe always runs
    assert ctx.result is None
    assert guard.receipts[-1].state == "observed"
    assert guard.catalog.tools["send_email"] == {"to", "body"}


def test_enforce_allowed_runs_tool_and_records_one_receipt():
    stub = _StubClient(outcome="allowed")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="maf")
    ran, ctx = _drive(guard, "read_file", {"path": "x"})
    assert ran is True  # call_next was awaited
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is True


def test_enforce_withheld_skips_tool_sets_result_and_records_one_receipt():
    stub = _StubClient(outcome="blocked", reason="blocked by policy")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="maf")
    ran, ctx = _drive(guard, "delete_account", {"account_id": "a9"})
    assert ran is False  # call_next NOT awaited -> tool never ran
    assert isinstance(ctx.result, str) and "withheld" in ctx.result
    assert len(guard.receipts) == 1
    assert guard.receipts[-1].state == "governed" and guard.receipts[-1].executed is False


def test_enforce_fail_closed_on_client_error():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="maf")
    ran, ctx = _drive(guard, "terminal", {"cmd": "ls"}, fail_closed=True)
    assert ran is False
    assert isinstance(ctx.result, str) and "fail-closed" in ctx.result


def test_enforce_fail_open_when_configured():
    stub = _StubClient(raises=True)
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="maf")
    ran, ctx = _drive(guard, "terminal", {"cmd": "ls"}, fail_closed=False)
    assert ran is True  # fail open -> call_next awaited


def test_unknown_outcome_fails_safe():
    stub = _StubClient(outcome="quarantined", reason="unknown future outcome")
    guard = Guard(client=stub, tenant="t", mode="enforce", agent="maf")
    ran, ctx = _drive(guard, "delete_account", {"account_id": "a9"})
    assert ran is False  # withheld -> tool never ran
    assert len(guard.receipts) == 1 and guard.receipts[-1].executed is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
