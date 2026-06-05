"""SDK-independent core of the LlamaIndex adapter.

The gate logic lives here so it can be unit-tested without
``llama-index-core`` installed: tests drive ``run_guard_tool_call`` with a
plain tool name, an args dict, and an async ``run_tool`` continuation.
``llama_index.py`` wires this into a ``GuardedAgentWorkflow`` that overrides
``AgentWorkflow.call_tool``.

Verified against llama-index-core main (2026-06-04): the pre-execution seam
is the ``call_tool`` ``@step`` which receives a ``ToolCall`` event
(``tool_name``, ``tool_kwargs``, ``tool_id``) and runs the tool via
``_call_tool``. This is a **middleware shape**: ``run_tool`` is the
continuation, exactly like the Agno adapter, but async.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..decision import Hold
from ..guard import Guard


async def run_guard_tool_call(
    guard: Guard,
    tool_name: str,
    tool_kwargs: dict,
    run_tool: Callable[[], Awaitable[Any]],
    fail_closed: bool = True,
) -> Any:
    """Gate one tool call through the KIFF guard, then run it.

    observe: record + learn, always ``await run_tool()`` and return result.
    enforce allowed: ``await run_tool()``, ``record_executed``, return result.
    enforce withheld: ``record_withheld`` and raise ``Hold`` (the tool never
      runs).
    fail_closed (enforce, default True): on guard/transport error, raise
      ``Hold`` so the tool does not run. ``fail_closed=False`` opts into
      fail-open (run the tool without a recorded decision). observe never
      blocks.
    """
    tool_name = tool_name or ""
    args = dict(tool_kwargs) if isinstance(tool_kwargs, dict) else {}

    if guard.mode == "observe":
        try:
            guard.observe(tool_name, args)
        except Exception:
            pass  # observe never blocks
        return await run_tool()

    # enforce
    try:
        decision = guard.decide_only(tool_name, args)
    except Exception as exc:
        if fail_closed:
            raise Hold(
                _error_decision(
                    f"KIFF guard unavailable; blocking {tool_name} "
                    f"(fail-closed): {exc}"
                )
            ) from exc
        return await run_tool()  # fail-open: no recorded decision

    if decision.withheld:
        guard.record_withheld(tool_name, args, decision)
        raise Hold(decision)

    guard.record_executed(tool_name, args, decision)
    return await run_tool()


def _error_decision(reason: str) -> Any:
    """A minimal Decision-shaped object for the fail-closed Hold. Uses the
    real Decision type so ``.withheld`` / ``.outcome`` behave correctly."""
    from ..decision import Decision

    return Decision(outcome="error", reason=reason)
