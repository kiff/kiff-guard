"""LangGraph / LangChain adapter — middleware (wrap_tool_call) shape.

Verified against the LangChain v1 middleware API (2026): `wrap_tool_call`,
`create_agent`, and the middleware types live in the **`langchain`**
package (v1.x), not `langgraph` — `langchain` depends on `langgraph`
underneath, but the imports below are satisfied by `langchain`. Install
with `pip install "kiff-guard[langgraph]"`, which pulls `langchain>=1.0,<2`.

    from langchain.agents.middleware import wrap_tool_call
    from langchain.tools.tool_node import ToolCallRequest
    from langchain.messages import ToolMessage

    @wrap_tool_call
    def my_mw(request: ToolCallRequest, handler) -> ToolMessage | Command:
        ...

- `request.tool_call["name"]` / `request.tool_call["args"]` carry the call.
- Calling `handler(request)` runs the tool and returns a ToolMessage.
- **Skip calling handler to short-circuit** — return a ToolMessage of
  your own and the tool never runs. This is the block path (the built-in
  `ShellAllowListMiddleware` does exactly this to reject shell commands).

So LangGraph is a *middleware-shape* adapter, like Agno: the guard runs
the tool via the handler continuation (`Guard.evaluate(run=...)`), and a
withheld decision returns a ToolMessage carrying the reason instead of
running. No `interrupt()` needed for the gate; the existing approval
machinery in the host app can still consume the ToolMessage outcome.

This module imports LangChain lazily (only inside the factory / only when
building a real ToolMessage), so importing kiff_guard never requires
langchain. The `langgraph` extra pulls in `langchain` (v1) for real use.
"""

from __future__ import annotations

from typing import Any, Callable

from ..decision import Hold
from ..guard import Guard


def kiff_wrap_tool_call(guard: Guard) -> Callable[[Any, Callable], Any]:
    """Return a callable matching LangChain's `wrap_tool_call` signature,
    backed by the given Guard.

    observe mode: runs the tool via the handler, records + learns, never
      blocks.
    enforce mode: on allowed, runs the tool; on withheld, returns a
      ToolMessage carrying the KIFF reason WITHOUT running the tool.

    Wrap it as middleware:

        from langchain.agents.middleware import wrap_tool_call
        from langchain.agents import create_agent
        from kiff_guard import Guard
        from kiff_guard.adapters.langgraph import kiff_wrap_tool_call

        guard = Guard(mode="observe")
        kiff_mw = wrap_tool_call(kiff_wrap_tool_call(guard))
        agent = create_agent(model=..., tools=[...], middleware=[kiff_mw])
    """

    def _wrap(request: Any, handler: Callable[[Any], Any]) -> Any:
        tool_call = getattr(request, "tool_call", None) or {}
        name = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        tool_call_id = tool_call.get("id", "")

        try:
            # Middleware shape: the guard runs the tool via the handler
            # continuation, exactly like Agno's tool_hooks.
            return guard.evaluate(name, args, run=lambda: handler(request))
        except Hold as hold:
            # Withheld in enforce mode: short-circuit by returning a
            # ToolMessage of our own — the tool never runs, and the model
            # sees the KIFF reason as the tool result.
            return _block_message(name, tool_call_id, hold.decision)

    return _wrap


def _block_message(tool_name: str, tool_call_id: str, decision: Any) -> Any:
    """Build a LangChain ToolMessage carrying the withheld reason. Imported
    lazily so the module loads without langchain installed (for tests)."""
    from langchain.messages import ToolMessage  # lazy import

    content = f"KIFF withheld {tool_name}: {decision.outcome} — {decision.reason}"
    # status="error" surfaces it as a failed tool call to the model.
    return ToolMessage(content=content, tool_call_id=tool_call_id, status="error")
