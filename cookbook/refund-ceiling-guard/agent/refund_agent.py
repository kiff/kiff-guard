"""refund_agent — a real LangGraph agent that issues refunds, guarded by KIFF.

Uses LangGraph's create_react_agent. The KIFF guard wraps the tool
function directly (evaluate pattern): before the tool body runs, the
guard calls kiff-decide. If blocked, it raises Hold which we catch and
return as a string result to the model.

Environment:
  OPENAI_API_KEY, KIFF_BASE_URL, KIFF_CLOUD_API_KEY, KIFF_CLOUD_URL, REFUND_APP_URL
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.decision import Hold

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
KIFF_CLOUD_API_KEY = os.environ.get("KIFF_CLOUD_API_KEY", "")
KIFF_CLOUD_URL = os.environ.get("KIFF_CLOUD_URL", "https://api.kiff.dev")
REFUND_APP_URL = os.environ.get("REFUND_APP_URL", "http://localhost:8082")


def _post(url: str, body: dict) -> dict:
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _get(url: str) -> dict:
    from urllib import request as urllib_request
    with urllib_request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def build_guard() -> Guard:
    """Build the KIFF guard in enforce mode."""
    tool_map = ToolMap().bind(
        "issue_refund",
        action="ISSUE_REFUND",
        entity_type="Order",
        entity_arg="order_id",
    )
    client = HTTPClient(api_key="local", tool_map=tool_map, base_url=KIFF_BASE_URL)
    guard = Guard(client=client, tenant="cookbook", agent="refund-agent", mode="enforce")

    if KIFF_CLOUD_API_KEY:
        try:
            cloud_client = HTTPClient(
                api_key=KIFF_CLOUD_API_KEY, tool_map=tool_map, base_url=KIFF_CLOUD_URL,
            )
            conn = cloud_client.connect_guard(
                agent_id="refund-agent", adapter="langgraph", mode="enforce",
                project="cookbook", environment="aws", workflow="refund-ceiling",
                sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def create_refund_agent(guard: Guard):
    """Create a LangGraph ReAct agent with the guarded issue_refund tool."""
    from langchain_openai import ChatOpenAI
    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent

    @tool
    def issue_refund(order_id: str, amount_cents: int) -> str:
        """Issue a refund for an order. amount_cents is how much to refund."""
        args = {"order_id": order_id, "amount_cents": amount_cents}

        def do_refund():
            result = _post(f"{REFUND_APP_URL}/refund", args)
            _post(f"{KIFF_BASE_URL}/v1/events/raw", {
                "order_id": order_id, "type": "REFUND_ISSUED",
                "actor_id": "refund-agent",
                "payload": {"amount_cents": amount_cents},
            })
            ledger = _get(f"{REFUND_APP_URL}/ledger")
            order = ledger.get("orders", {}).get(order_id, {})
            if order and order.get("refunded_cents", 0) >= order.get("amount_cents", 0):
                _post(f"{KIFF_BASE_URL}/v1/events/raw", {
                    "order_id": order_id, "type": "ORDER_FULLY_REFUNDED",
                    "actor_id": "system",
                })
            return json.dumps(result)

        try:
            return guard.evaluate("issue_refund", args, run=do_refund)
        except Hold as h:
            return f"BLOCKED by KIFF: {h.decision.outcome} — {h.decision.reason}"

    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = create_react_agent(model=model, tools=[issue_refund])
    return agent


def run_agent(agent, message: str) -> str:
    """Invoke the agent and return the final response."""
    result = agent.invoke({"messages": [("human", message)]})
    messages = result.get("messages", [])
    if messages:
        return messages[-1].content
    return ""
