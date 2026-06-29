"""refund_agent — Agno agent with the KIFF guard via agno_hook.

The agent has one tool: issue_refund(order_id, amount_cents, reason).
KIFF gates each refund attempt. ISSUE_REFUND is allowed only while the
order is PAID; once it advances to REFUNDED (or was never PAID), KIFF
blocks and the agent cannot pay out again. The boundary is what lets
you hand the agent the refund route at all.

Model is selectable: MODEL_PROVIDER = openai (default) | bedrock |
claude. The KIFF
tool hook is model-agnostic, so swapping the model is a one-liner.

Environment:
  MODEL_PROVIDER, MODEL_ID, OPENAI_API_KEY (openai),
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION (bedrock/claude),
  KIFF_BASE_URL, KIFF_CLOUD_API_KEY, KIFF_CLOUD_URL, REFUND_APP_URL
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                 "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.adapters.agno import agno_hook

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
KIFF_CLOUD_API_KEY = os.environ.get("KIFF_CLOUD_API_KEY", "")
KIFF_CLOUD_URL = os.environ.get("KIFF_CLOUD_URL", "https://api.kiff.dev")
REFUND_APP_URL = os.environ.get("REFUND_APP_URL", "http://localhost:8082")


def _post(url, body):
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def make_model():
    """Pick the model from env.

    The guard hook does not care which model proposes the tool call,
    so OpenAI (default, no AWS needed) and Bedrock are interchangeable.
    """
    provider = os.environ.get("MODEL_PROVIDER", "openai").lower()
    model_id = os.environ.get("MODEL_ID", "").strip()
    if provider == "bedrock":
        from agno.models.aws import AwsBedrock
        return AwsBedrock(id=model_id or "amazon.nova-pro-v1:0")
    if provider in ("claude", "bedrock-claude"):
        from agno.models.aws import Claude
        return Claude(id=model_id or "global.anthropic.claude-sonnet-4-5-20250929-v1:0")
    from agno.models.openai import OpenAIChat
    return OpenAIChat(id=model_id or "gpt-4o-mini")


def build_guard() -> Guard:
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
                agent_id="refund-agent", adapter="agno", mode="enforce",
                project="cookbook", environment="aws", workflow="refund-enablement",
                sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def create_refund_agent(guard: Guard):
    """Create an Agno agent with the guarded issue_refund tool."""
    from agno.agent import Agent
    from agno.tools import tool

    @tool
    def issue_refund(order_id: str, amount_cents: int, reason: str) -> str:
        """Issue a refund on an order. amount_cents is the refund amount."""
        result = _post(f"{REFUND_APP_URL}/refund", {
            "order_id": order_id,
            "amount_cents": amount_cents,
            "reason": reason,
        })
        return json.dumps(result)

    agent = Agent(
        model=make_model(),
        tools=[issue_refund],
        tool_hooks=[agno_hook(guard)],
        instructions=[
            "You are a refund agent. When asked to refund an order, "
            "call issue_refund with the order_id, amount_cents, and a brief reason.",
        ],
    )
    return agent


def run_agent(agent, message: str) -> str:
    response = agent.run(message)
    if hasattr(response, "content"):
        return response.content
    return str(response)
