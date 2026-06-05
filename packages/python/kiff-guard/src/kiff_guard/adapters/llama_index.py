"""LlamaIndex adapter — middleware shape (async).

Verified against llama-index-core main (2026-06-04):
  github.com/run-llama/llama_index/blob/main/llama-index-core/
    llama_index/core/agent/workflow/multi_agent_workflow.py
    llama_index/core/agent/workflow/workflow_events.py
    llama_index/core/agent/workflow/function_agent.py

## Seam

The pre-execution seam in LlamaIndex's AgentWorkflow is the ``call_tool``
workflow step:

    @step
    async def call_tool(self, ctx: Context, ev: ToolCall) -> ToolCallResult:

``ToolCall`` carries ``tool_name``, ``tool_kwargs``, and ``tool_id``.
The step resolves the tool, calls it, and returns a ``ToolCallResult``.

The guard sits *inside* this step, before ``_call_tool`` runs, by
subclassing ``AgentWorkflow`` and overriding ``call_tool``. This is a
**middleware shape**: the guard closure over ``_call_tool`` is the
continuation; in enforce mode a withheld decision raises ``Hold`` instead
of proceeding.

## Block contract

``ToolCallResult`` is the step's return type. When KIFF withholds, the
override raises ``Hold`` so the tool body never runs. The caller
(``aggregate_tool_results``) does not receive a result for this call; the
exception propagates up through the workflow handler, matching the
fail-safe principle (unknown future outcomes also withhold).

An alternative that stays within the workflow without raising would be to
return a synthetic error ``ToolCallResult``; however, that would silently
hide the withheld decision from the caller. Raising is the honest path.

## Shape

- **middleware**: the guard runs the tool via the ``_call_tool``
  continuation, exactly like the Agno adapter. Subclassing overrides a
  single step method; no patching.
- All workflow logic is **async**; the adapter is fully async to match.
- Lazy import: this module imports nothing from LlamaIndex until
  ``GuardedAgentWorkflow`` is instantiated, so ``import kiff_guard`` works
  without ``llama-index-core`` installed. The ``llama-index`` extra pulls
  the framework in for real use.

## Usage

    from llama_index.core.agent.workflow import FunctionAgent
    from llama_index.llms.openai import OpenAI
    from kiff_guard import Guard
    from kiff_guard.adapters.llama_index import GuardedAgentWorkflow

    guard = Guard(mode="observe")          # zero-config audit
    workflow = GuardedAgentWorkflow(
        agents=[FunctionAgent(tools=[...], llm=OpenAI(model="gpt-4o-mini"))],
        guard=guard,
    )
    result = await workflow.run(user_msg="...")

For enforce mode, a withheld KIFF decision raises ``Hold``; handle it in
your application to surface the reason to the caller.
"""

from __future__ import annotations

from typing import Any

from ..decision import Hold
from ..guard import Guard


class GuardedAgentWorkflow:
    """A thin factory + subclass wrapper that injects a KIFF Guard into
    LlamaIndex's AgentWorkflow.call_tool step.

    Instantiate this in place of AgentWorkflow. All constructor arguments
    are forwarded to AgentWorkflow except ``guard`` and ``fail_closed``.

    Parameters
    ----------
    guard:
        A configured Guard instance (observe or enforce mode).
    fail_closed:
        In enforce mode, if the guard itself errors (transport failure,
        timeout), withhold the tool call (True, default) or allow it
        (False). observe mode is always fail-open per the SDK invariant.
    **workflow_kwargs:
        Forwarded verbatim to AgentWorkflow.__init__.
    """

    def __new__(
        cls,
        *,
        guard: Guard,
        fail_closed: bool = True,
        **workflow_kwargs: Any,
    ) -> Any:  # returns a real AgentWorkflow subclass instance
        # Lazy import — AgentWorkflow is only imported here, so
        # `import kiff_guard` never requires llama-index-core.
        from llama_index.core.agent.workflow import AgentWorkflow  # lazy
        from llama_index.core.workflow import Context, step  # lazy
        from llama_index.core.agent.workflow.workflow_events import (  # lazy
            ToolCall,
            ToolCallResult,
        )

        _guard = guard
        _fail_closed = fail_closed

        class _GuardedWorkflow(AgentWorkflow):
            """AgentWorkflow subclass that gates every tool call through
            the KIFF guard before execution."""

            @step
            async def call_tool(
                self, ctx: Context, ev: ToolCall
            ) -> ToolCallResult:
                """Override AgentWorkflow.call_tool to insert KIFF gate."""
                # Emit the ToolCall event to the stream (base class does this
                # too; we preserve the behaviour).
                ctx.write_event_to_stream(
                    ToolCall(
                        tool_name=ev.tool_name,
                        tool_kwargs=ev.tool_kwargs,
                        tool_id=ev.tool_id,
                    )
                )

                # Resolve the tool (mirrors base class logic).
                current_agent_name = await ctx.store.get("current_agent_name")
                tools = await self.get_tools(current_agent_name, ev.tool_name)
                tools_by_name = {tool.metadata.name: tool for tool in tools}

                if ev.tool_name not in tools_by_name:
                    # Unknown tool — let the base class produce the standard
                    # error ToolCallResult without a KIFF decision (no action
                    # contract to evaluate).
                    from llama_index.core.tools import ToolOutput  # lazy

                    result = ToolOutput(
                        content=(
                            f"Tool {ev.tool_name} not found. "
                            "Please select a tool that is available."
                        ),
                        tool_name=ev.tool_name,
                        raw_input=ev.tool_kwargs,
                        raw_output=None,
                        is_error=True,
                    )
                    result_ev = ToolCallResult(
                        tool_name=ev.tool_name,
                        tool_kwargs=ev.tool_kwargs,
                        tool_id=ev.tool_id,
                        tool_output=result,
                        return_direct=False,
                    )
                    ctx.write_event_to_stream(result_ev)
                    return result_ev

                tool = tools_by_name[ev.tool_name]

                # --- KIFF gate -------------------------------------------
                async def _run_tool() -> ToolOutput:
                    return await self._call_tool(ctx, tool, ev.tool_kwargs)

                if _guard.mode == "observe":
                    try:
                        _guard.observe(ev.tool_name, ev.tool_kwargs)
                    except Exception:
                        pass  # observe never blocks
                    result = await _run_tool()
                else:
                    # enforce
                    try:
                        decision = _guard.decide_only(ev.tool_name, ev.tool_kwargs)
                    except Exception as exc:
                        if _fail_closed:
                            raise Hold(
                                decision=type("_D", (), {
                                    "outcome": "error",
                                    "reason": f"KIFF guard unavailable (fail-closed): {exc}",
                                    "withheld": True,
                                })()
                            ) from exc
                        # fail-open: proceed without a recorded decision
                        result = await _run_tool()
                    else:
                        if decision.withheld:
                            _guard.record_withheld(
                                ev.tool_name, ev.tool_kwargs, decision
                            )
                            raise Hold(decision=decision)
                        _guard.record_executed(
                            ev.tool_name, ev.tool_kwargs, decision
                        )
                        result = await _run_tool()
                # ---------------------------------------------------------

                result_ev = ToolCallResult(
                    tool_name=ev.tool_name,
                    tool_kwargs=ev.tool_kwargs,
                    tool_id=ev.tool_id,
                    tool_output=result,
                    return_direct=(
                        tool.metadata.return_direct if tool else False
                    ),
                )
                ctx.write_event_to_stream(result_ev)
                return result_ev

        # Instantiate the dynamically-built subclass with the forwarded args.
        return _GuardedWorkflow(**workflow_kwargs)
