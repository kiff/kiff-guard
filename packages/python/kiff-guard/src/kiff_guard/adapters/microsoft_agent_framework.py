"""Microsoft Agent Framework (MAF) adapter — FunctionMiddleware
(vote shape, async).

Verified against the installed ``agent-framework-core`` package
(introspected ``agent_framework.FunctionMiddleware`` +
``FunctionInvocationContext``):

  - The pre-execution seam is **function middleware**: subclass
    ``FunctionMiddleware`` and implement
    ``async def process(self, context, call_next)``. Attach via
    ``Agent(..., middleware=[kiff_guard_middleware(guard)])``.
  - ``context.function.name`` is the tool name; ``context.arguments``
    are the validated args (a pydantic ``BaseModel`` or a ``Mapping``).
  - To **run** the tool: ``await call_next()``. To **block**: set
    ``context.result`` and do **not** call ``call_next`` (the documented
    override pattern; the SDK's own caching example sets
    ``context.result`` and stops the pipeline).

The decision logic lives in ``microsoft_agent_framework_core`` so it can
be unit-tested without the SDK installed; this module is the thin wiring
to the real ``FunctionMiddleware`` base class. KIFF maps to the **vote**
behaviour (decide, then run via ``call_next`` only when allowed), using
the guard's ``observe()`` / ``decide_only()`` + ``record_executed`` /
``record_withheld`` — one receipt per call.

``process`` is async; the guard's primitives are sync (a fast HTTP
decide call), matching the sync client the other adapters use.

This module imports ``agent_framework`` **lazily** (only when building
the middleware subclass), so importing ``kiff_guard`` never requires
agent-framework-core. The ``microsoft-agent-framework`` extra
(``pip install "kiff-guard[microsoft-agent-framework]"``) pulls it in.
"""

from __future__ import annotations

from typing import Any

from .microsoft_agent_framework_core import run_guard_middleware


def kiff_guard_middleware(guard: Any, fail_closed: bool = True) -> Any:
    """Return an instance of a ``FunctionMiddleware`` subclass wired to
    the given Guard, ready to pass to ``Agent(middleware=[...])``:

        from agent_framework import Agent
        from kiff_guard import Guard
        from kiff_guard.adapters.microsoft_agent_framework import kiff_guard_middleware

        guard = Guard(mode="observe")     # zero-config audit
        agent = Agent(client=..., name="assistant", tools=[...],
                      middleware=[kiff_guard_middleware(guard)])

    observe mode: records + learns every call, always runs the tool.
    enforce mode: a withheld KIFF decision sets ``context.result`` and
      skips ``call_next`` (tool never runs); an allowed decision runs the
      tool and records execution.
    fail_closed (enforce, default True): on a guard/transport error,
      block. observe always runs.

    Imports agent-framework-core lazily; requires it installed.
    """
    from agent_framework import FunctionInvocationContext, FunctionMiddleware  # lazy import

    class _KiffGuardMiddleware(FunctionMiddleware):
        async def process(self, context: FunctionInvocationContext, call_next: Any) -> None:
            await run_guard_middleware(guard, context, call_next, fail_closed=fail_closed)

    return _KiffGuardMiddleware()
