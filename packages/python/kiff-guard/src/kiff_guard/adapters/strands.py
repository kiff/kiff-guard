"""Strands Agents adapter — BeforeToolCallEvent hook (vote shape).

Verified against the installed ``strands-agents`` SDK (introspected
``strands.hooks``):

  - The pre-execution seam is the ``BeforeToolCallEvent`` hook. Strands
    fires it just before it executes a tool; the agent runs the tool
    itself, so the hook only *votes*.
  - ``event.tool_use`` is a ``ToolUse`` dict carrying ``name``,
    ``input`` (the args), and ``toolUseId``.
  - To **block**: set ``event.cancel_tool = "<message>"`` — Strands
    cancels the call and places the message into a tool result with an
    error status. Leaving it unset lets the tool run.
  - Hooks are registered via a ``HookProvider`` whose
    ``register_hooks(registry)`` calls
    ``registry.add_callback(BeforeToolCallEvent, cb)``; attach with
    ``Agent(hooks=[provider])``.

So Strands is a **vote shape** (like Hermes / OpenAI / ADK), not a wrap
shape: the adapter uses the guard's ``observe()`` / ``decide_only()``
primitives + ``record_executed`` / ``record_withheld`` — one receipt per
call — never ``evaluate(run=...)``.

This module imports ``strands`` **lazily** (only inside
``register_kiff_guard`` when building the provider), so importing
``kiff_guard`` never requires strands-agents. The ``strands`` extra
(``pip install "kiff-guard[strands]"``) pulls it in for real use.
"""

from __future__ import annotations

from typing import Any, Callable

from ..guard import Guard


def kiff_before_tool_call(guard: Guard, fail_closed: bool = True) -> Callable[[Any], None]:
    """Return a callback for Strands' ``BeforeToolCallEvent``, backed by
    the given Guard. The callback mutates the event in place
    (``event.cancel_tool``) — Strands' block contract.

    observe mode: records + learns every call, never cancels.
    enforce mode: on a withheld decision sets ``event.cancel_tool`` to a
      reason string so the tool never runs; on allowed, records that the
      tool ran and leaves the event untouched.

    ``fail_closed`` (enforce only): on a guard/transport error, cancel
    the tool with an explanatory message. observe always fails open.
    """

    def _callback(event: Any) -> None:
        tool_use = getattr(event, "tool_use", None) or {}
        tool_name = tool_use.get("name", "") if isinstance(tool_use, dict) else ""
        args = tool_use.get("input", {}) if isinstance(tool_use, dict) else {}
        args = args if isinstance(args, dict) else {}

        if guard.mode == "observe":
            try:
                guard.observe(tool_name, args)
            except Exception:
                pass  # observe never blocks
            return

        # enforce
        try:
            decision = guard.decide_only(tool_name, args)
        except Exception as exc:
            if fail_closed:
                event.cancel_tool = (
                    f"KIFF guard unavailable; blocking {tool_name} (fail-closed): {exc}"
                )
            return
        if decision.withheld:
            guard.record_withheld(tool_name, args, decision)
            event.cancel_tool = (
                f"KIFF withheld {tool_name}: {decision.outcome} — {decision.reason}"
            )
            return
        # allowed: Strands will run the tool next. Record that it ran.
        guard.record_executed(tool_name, args, decision)

    return _callback


def kiff_hook_provider(guard: Guard, fail_closed: bool = True) -> Any:
    """Return a Strands ``HookProvider`` that registers the KIFF guard on
    ``BeforeToolCallEvent``. Pass it to the agent:

        from strands import Agent
        from kiff_guard import Guard
        from kiff_guard.adapters.strands import kiff_hook_provider

        guard = Guard(mode="observe")     # zero-config audit
        agent = Agent(model=..., tools=[...], hooks=[kiff_hook_provider(guard)])

    Imports strands lazily; requires ``strands-agents`` installed.
    """
    from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry  # lazy import

    callback = kiff_before_tool_call(guard, fail_closed=fail_closed)

    class _KiffGuardHooks(HookProvider):
        def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
            registry.add_callback(BeforeToolCallEvent, callback)

    return _KiffGuardHooks()
