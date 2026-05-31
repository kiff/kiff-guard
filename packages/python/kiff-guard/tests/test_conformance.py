"""Run every shipped adapter through the conformance suite.

This is the durability contract: each adapter provides a tiny `drive`
shim (invoke its seam once, report whether the tool body ran) and the
shared invariants in kiff_guard.conformance do the rest. A new adapter
is "done" when it has a drive shim here and passes.

All drivers are framework-free (they mimic each framework's call shape),
so this runs with no agent framework installed."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Guard, Hold  # noqa: E402
from kiff_guard.conformance import AdapterDriver, run_conformance  # noqa: E402
from kiff_guard.adapters.agno import agno_hook  # noqa: E402
from kiff_guard.adapters.hermes import hermes_pre_tool_call  # noqa: E402
from kiff_guard.adapters.openai_agents_core import build_guardrail_callback  # noqa: E402
import kiff_guard.adapters.langgraph as lg  # noqa: E402


# --- Agno: middleware. hook(name, func, args); func runs the tool. --------
def _drive_agno(guard, tool, args, *, will_run):
    ran = {"v": False}

    def func(**kwargs):
        ran["v"] = True
        return "ok"

    hook = agno_hook(guard)
    try:
        hook(tool, func, args)
    except Hold:
        pass  # enforce withheld -> middleware raises Hold; tool didn't run
    return ran["v"]


# --- Hermes: vote. cb(tool, args, task_id); returns block dict or None. ---
def _drive_hermes(guard, tool, args, *, will_run):
    cb = hermes_pre_tool_call(guard)
    out = cb(tool, args, task_id="t")
    # Hermes doesn't run the tool itself; "ran" = not blocked.
    blocked = isinstance(out, dict) and out.get("action") == "block"
    return not blocked


# --- OpenAI: vote via tool input guardrail. allow()/reject_content(). -----
class _FakeOutputs:
    @staticmethod
    def allow(output_info=None):
        return {"behavior": "allow"}

    @staticmethod
    def reject_content(message, output_info=None):
        return {"behavior": "reject_content", "message": message}


def _drive_openai(guard, tool, args, *, will_run):
    import json

    class _Ctx:
        def __init__(self, t, a):
            self.tool_name = t
            self.tool_arguments = json.dumps(a)
            self.tool_call_id = "tc"

    class _Data:
        def __init__(self, t, a):
            self.context = _Ctx(t, a)
            self.agent = None

    cb = build_guardrail_callback(guard, outputs=_FakeOutputs)
    out = cb(_Data(tool, args))
    # OpenAI doesn't run the tool itself; "ran" = allowed.
    return out["behavior"] == "allow"


# --- LangGraph: middleware via wrap_tool_call; handler runs the tool. -----
def _drive_langgraph(guard, tool, args, *, will_run):
    ran = {"v": False}

    class _Req:
        def __init__(self, t, a):
            self.tool_call = {"name": t, "args": a, "id": "tc"}

    def handler(request):
        ran["v"] = True
        return "ok"

    # Stub the lazy ToolMessage builder so no langchain is needed.
    lg._block_message = lambda tool_name, tool_call_id, decision: {"__blocked__": True}
    wrap = lg.kiff_wrap_tool_call(guard)
    wrap(_Req(tool, args), handler)
    return ran["v"]


def test_agno_conformance():
    run_conformance(AdapterDriver(name="agno", drive=_drive_agno))


def test_hermes_conformance():
    run_conformance(AdapterDriver(name="hermes", drive=_drive_hermes))


def test_openai_conformance():
    run_conformance(AdapterDriver(name="openai-agents", drive=_drive_openai))


def test_langgraph_conformance():
    run_conformance(AdapterDriver(name="langgraph", drive=_drive_langgraph))


# --- Google ADK: vote. before_tool_callback(tool, args, tool_context);
#     returns a dict to block, None to allow. ADK runs the tool itself. --
def _drive_google_adk(guard, tool, args, *, will_run):
    from kiff_guard.adapters.google_adk import kiff_before_tool_callback

    class _Tool:
        def __init__(self, name):
            self.name = name

    cb = kiff_before_tool_callback(guard)
    out = cb(tool=_Tool(tool), args=args, tool_context=None)
    # ADK doesn't run the tool itself; "ran" = not blocked (None = proceed).
    return out is None


# --- Pydantic AI: vote. before_tool_execute hook; returns args to allow,
#     raises SkipToolExecution to block. The framework runs the tool. -----
class _FakeSkip(Exception):
    pass


def _drive_pydantic_ai(guard, tool, args, *, will_run):
    from kiff_guard.adapters.pydantic_ai import kiff_before_tool_execute

    class _Call:
        def __init__(self, name):
            self.tool_name = name

    # Inject a test SkipToolExecution so no pydantic-ai install is needed.
    hook = kiff_before_tool_execute(guard, skip_factory=lambda result: _FakeSkip(result))
    try:
        hook(ctx=None, call=_Call(tool), tool_def=None, args=args)
    except _FakeSkip:
        return False  # withheld -> tool skipped
    return True  # returned args -> tool will run


def test_google_adk_conformance():
    run_conformance(AdapterDriver(name="google-adk", drive=_drive_google_adk))


def test_pydantic_ai_conformance():
    run_conformance(AdapterDriver(name="pydantic-ai", drive=_drive_pydantic_ai))


# --- Strands: vote. BeforeToolCallEvent; callback sets event.cancel_tool
#     to block. Strands runs the tool itself. ------------------------------
def _drive_strands(guard, tool, args, *, will_run):
    from kiff_guard.adapters.strands import kiff_before_tool_call

    class _Event:
        def __init__(self, name, a):
            self.tool_use = {"name": name, "input": a, "toolUseId": "tu"}
            self.cancel_tool = False

    cb = kiff_before_tool_call(guard)
    ev = _Event(tool, args)
    cb(ev)
    # Strands doesn't run the tool itself; "ran" = not cancelled.
    return not bool(ev.cancel_tool)


# --- Haystack: vote. ConfirmationStrategy.run(...) -> decision.execute. ----
def _drive_haystack(guard, tool, args, *, will_run):
    from kiff_guard.adapters.haystack import kiff_confirmation_strategy

    class _Dec:
        def __init__(self, execute):
            self.execute = execute

    strategy = kiff_confirmation_strategy(
        guard, decision_factory=lambda name, tcid, execute, feedback="": _Dec(execute)
    )
    out = strategy.run(tool_name=tool, tool_description="", tool_params=args, tool_call_id="tc")
    # Haystack runs the tool iff execute is True.
    return bool(out.execute)


# --- Microsoft Agent Framework: middleware (async). Drives the real core
#     (run_guard_middleware) with a duck-typed context + async call_next. ---
def _drive_microsoft_agent_framework(guard, tool, args, *, will_run):
    import asyncio

    from kiff_guard.adapters.microsoft_agent_framework_core import run_guard_middleware

    ran = {"v": False}

    class _Fn:
        def __init__(self, name):
            self.name = name

    class _Ctx:
        def __init__(self, name, a):
            self.function = _Fn(name)
            self.arguments = a
            self.result = None

    async def call_next():
        ran["v"] = True

    asyncio.run(run_guard_middleware(guard, _Ctx(tool, args), call_next))
    return ran["v"]


def test_strands_conformance():
    run_conformance(AdapterDriver(name="strands", drive=_drive_strands))


def test_haystack_conformance():
    run_conformance(AdapterDriver(name="haystack", drive=_drive_haystack))


def test_microsoft_agent_framework_conformance():
    run_conformance(AdapterDriver(name="microsoft-agent-framework", drive=_drive_microsoft_agent_framework))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
