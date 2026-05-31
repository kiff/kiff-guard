"""Haystack Agents adapter — ConfirmationStrategy (vote shape).

Verified against the installed ``haystack-ai`` Agent + human-in-the-loop
types (introspected
``haystack.components.agents`` + ``haystack.human_in_the_loop``):

  - The pre-execution seam is a ``ConfirmationStrategy`` passed to
    ``Agent(confirmation_strategies={tool_name: strategy})``. Haystack
    calls ``strategy.run(*, tool_name, tool_description, tool_params,
    tool_call_id=None, confirmation_strategy_context=None)`` before it
    executes the tool, and runs the tool itself based on the returned
    decision.
  - ``run`` returns a ``ToolExecutionDecision(tool_name, execute: bool,
    tool_call_id=None, feedback=None, final_tool_params=None)``.
    ``execute=True`` runs the tool (optionally with ``final_tool_params``);
    ``execute=False`` blocks it and surfaces ``feedback`` as the reason.

So Haystack is a **vote shape**: the agent runs the tool; the strategy
votes via ``execute``. The adapter uses the guard's ``observe()`` /
``decide_only()`` primitives + ``record_executed`` / ``record_withheld``
— one receipt per call — never ``evaluate(run=...)``.

This module imports ``haystack`` **lazily** (only inside
``kiff_confirmation_strategy`` when building the decision), so importing
``kiff_guard`` never requires haystack-ai. The ``haystack`` extra
(``pip install "kiff-guard[haystack]"``) pulls it in for real use.
"""

from __future__ import annotations

from typing import Any


def _decision(tool_name: str, tool_call_id: Any, execute: bool, feedback: str = "") -> Any:
    """Build a Haystack ToolExecutionDecision. Imported lazily so the
    module loads without haystack-ai installed (for tests)."""
    from haystack.human_in_the_loop.dataclasses import ToolExecutionDecision  # lazy import

    return ToolExecutionDecision(
        tool_name=tool_name, execute=execute, tool_call_id=tool_call_id, feedback=feedback or None
    )


def kiff_confirmation_strategy(guard: Any, fail_closed: bool = True, decision_factory: Any = None) -> Any:
    """Return a Haystack ``ConfirmationStrategy`` (an object with a
    ``run`` method) backed by the given Guard, ready to register:

        from haystack.components.agents import Agent
        from kiff_guard import Guard
        from kiff_guard.adapters.haystack import kiff_confirmation_strategy

        guard = Guard(mode="observe")     # zero-config audit
        strategy = kiff_confirmation_strategy(guard)
        agent = Agent(chat_generator=..., tools=[refund_order],
                      confirmation_strategies={"refund_order": strategy})

    observe mode: records + learns every call, always returns
      ``execute=True`` (never blocks).
    enforce mode: on a withheld KIFF decision returns ``execute=False``
      with the reason as feedback so the tool never runs; on allowed,
      records execution and returns ``execute=True``.
    fail_closed (enforce, default True): on a guard/transport error,
      return ``execute=False`` — a control tower must not wave traffic
      through when its decision path is down. observe always allows.

    ``decision_factory`` is injectable so tests run without haystack-ai
    installed; it defaults to building the SDK's ToolExecutionDecision.
    """

    build = decision_factory if decision_factory is not None else _decision

    class _KiffConfirmationStrategy:
        def run(
            self,
            *,
            tool_name: str,
            tool_description: str = "",
            tool_params: Any = None,
            tool_call_id: Any = None,
            confirmation_strategy_context: Any = None,
        ) -> Any:
            args = tool_params if isinstance(tool_params, dict) else {}

            if guard.mode == "observe":
                try:
                    guard.observe(tool_name, args)
                except Exception:
                    pass  # observe never blocks
                return build(tool_name, tool_call_id, True, "")

            # enforce
            try:
                decision = guard.decide_only(tool_name, args)
            except Exception as exc:
                if fail_closed:
                    return build(
                        tool_name,
                        tool_call_id,
                        False,
                        f"KIFF guard unavailable; blocking {tool_name} (fail-closed): {exc}",
                    )
                return build(tool_name, tool_call_id, True, "")
            if decision.withheld:
                guard.record_withheld(tool_name, args, decision)
                return build(
                    tool_name,
                    tool_call_id,
                    False,
                    f"KIFF withheld {tool_name}: {decision.outcome} — {decision.reason}",
                )
            # allowed: Haystack will run the tool next. Record that.
            guard.record_executed(tool_name, args, decision)
            return build(tool_name, tool_call_id, True, "")

    return _KiffConfirmationStrategy()
