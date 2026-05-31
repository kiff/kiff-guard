"""SDK-independent core of the Microsoft Agent Framework adapter.

The middleware logic lives here so it can be unit-tested without
``agent-framework-core`` installed: tests pass a duck-typed ``context``
(with ``.function.name``, ``.arguments``, ``.result``) and an async
``call_next``. ``microsoft_agent_framework.py`` wires this to the real
``FunctionMiddleware`` base class.

Verified against the installed ``agent_framework`` package: a
``FunctionMiddleware.process(self, context, call_next)`` runs the tool by
awaiting ``call_next()`` and blocks by setting ``context.result`` and not
calling ``call_next`` (the SDK's own caching example does exactly this).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def args_to_dict(arguments: Any) -> dict:
    """Normalize MAF's validated arguments (a pydantic BaseModel or a
    Mapping) into a plain dict for the guard + catalog."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return dict(arguments)
    dump = getattr(arguments, "model_dump", None)  # pydantic BaseModel
    if callable(dump):
        try:
            d = dump()
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    try:
        return dict(arguments)  # generic Mapping
    except Exception:
        return {}


async def run_guard_middleware(
    guard: Any,
    context: Any,
    call_next: Callable[[], Awaitable[None]],
    fail_closed: bool = True,
) -> None:
    """The function-middleware body, operating on a duck-typed MAF
    ``context`` (``.function.name``, ``.arguments``, ``.result``) and an
    async ``call_next``.

    observe: record + learn, always ``await call_next()``.
    enforce allowed: ``await call_next()`` then ``record_executed``.
    enforce withheld: set ``context.result`` to the refusal, skip
      ``call_next`` (the tool never runs), ``record_withheld``.
    fail_closed (enforce): on guard error, set result + skip call_next.
    """
    tool_name = getattr(getattr(context, "function", None), "name", "") or ""
    args = args_to_dict(getattr(context, "arguments", None))

    if guard.mode == "observe":
        try:
            guard.observe(tool_name, args)
        except Exception:
            pass  # observe never blocks
        await call_next()
        return

    # enforce
    try:
        decision = guard.decide_only(tool_name, args)
    except Exception as exc:
        if fail_closed:
            context.result = (
                f"KIFF guard unavailable; blocking {tool_name} (fail-closed): {exc}"
            )
            return  # skip call_next -> tool does not run
        await call_next()
        return
    if decision.withheld:
        guard.record_withheld(tool_name, args, decision)
        context.result = (
            f"KIFF withheld {tool_name}: {decision.outcome} — {decision.reason}"
        )
        return  # skip call_next -> tool does not run
    # allowed: run the tool, then record that it ran.
    await call_next()
    guard.record_executed(tool_name, args, decision)
