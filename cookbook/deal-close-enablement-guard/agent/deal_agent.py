"""deal_agent — Agno (v2) agent with the KIFF guard via agno_hook.

The agent has one tool: apply_discount(deal_id, percent, reason).
KIFF gates each discount attempt. APPLY_DISCOUNT is allowed only while the
deal is OPEN; once a discount is applied the deal advances to DISCOUNTED
(or the deal was never qualified), and KIFF declines — the agent cannot
stack another discount. The boundary is what lets you put the agent on
closing deals at all: it grants the closing discount, it does not give
margin away twice.

Built on Agno v2 (>=2.6, the kiff-guard agno extra). Model is selectable:
MODEL_PROVIDER = openai (default) | bedrock. The KIFF tool hook is
model-agnostic, so swapping the model is a one-liner.

Environment:
  MODEL_PROVIDER, MODEL_ID, OPENAI_API_KEY (openai),
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION (bedrock),
  KIFF_BASE_URL, KIFF_CLOUD_API_KEY, KIFF_CLOUD_URL, DEAL_APP_URL
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
DEAL_APP_URL = os.environ.get("DEAL_APP_URL", "http://localhost:8082")


def _post(url, body):
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def make_model():
    """Pick the model from env.

    The guard hook does not care which model proposes the tool call, so
    OpenAI (default, no AWS needed) and Bedrock are interchangeable. For
    Bedrock-hosted Claude, set MODEL_PROVIDER=bedrock and MODEL_ID to a
    `us.anthropic.claude-*` id.
    """
    provider = os.environ.get("MODEL_PROVIDER", "openai").lower()
    model_id = os.environ.get("MODEL_ID", "").strip()
    region = os.environ.get("AWS_REGION", "us-east-1")
    if provider == "bedrock":
        import boto3
        from agno.models.aws import AwsBedrock
        # Method 3 (boto3 Session) from the Agno docs: pass an explicit
        # session so the full credential chain is used (env, profile, and
        # an instance role via IMDS, which carries a session token).
        return AwsBedrock(id=model_id or "amazon.nova-pro-v1:0",
                          session=boto3.Session(region_name=region))
    from agno.models.openai import OpenAIChat
    return OpenAIChat(id=model_id or "gpt-4o-mini")


def build_guard() -> Guard:
    tool_map = ToolMap().bind(
        "apply_discount",
        action="APPLY_DISCOUNT",
        entity_type="Deal",
        entity_arg="deal_id",
    )
    client = HTTPClient(api_key="local", tool_map=tool_map, base_url=KIFF_BASE_URL)
    guard = Guard(client=client, tenant="cookbook", agent="deal-agent", mode="enforce")

    if KIFF_CLOUD_API_KEY:
        try:
            cloud_client = HTTPClient(
                api_key=KIFF_CLOUD_API_KEY, tool_map=tool_map, base_url=KIFF_CLOUD_URL,
            )
            cloud_guard = Guard(
                client=cloud_client, tenant="cloud", agent="deal-agent",
                mode="enforce", catalog=guard.catalog,
            )
            conn = cloud_guard.connect(
                adapter="agno", project="cookbook", environment="aws",
                workflow="deal-close-enablement", sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def create_deal_agent(guard: Guard):
    """Create an Agno agent with the guarded apply_discount tool."""
    from agno.agent import Agent
    from agno.tools import tool

    @tool
    def apply_discount(deal_id: str, percent: int, reason: str) -> str:
        """Apply a closing discount to a deal. percent is the discount percentage."""
        result = _post(f"{DEAL_APP_URL}/discount", {
            "deal_id": deal_id,
            "percent": percent,
            "reason": reason,
        })
        return json.dumps(result)

    agent = Agent(
        model=make_model(),
        tools=[apply_discount],
        tool_hooks=[agno_hook(guard)],
        instructions=[
            "You are a sales closing agent. When asked to close a deal with a "
            "discount, call apply_discount with the deal_id, percent, and a brief reason.",
        ],
    )
    return agent


def run_agent(agent, message: str) -> str:
    response = agent.run(message)
    if hasattr(response, "content"):
        return response.content
    return str(response)
