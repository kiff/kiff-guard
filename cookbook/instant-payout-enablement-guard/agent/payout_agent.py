"""payout_agent — Agno (v2) agent with the KIFF guard via agno_hook.

The agent has one tool: disburse_payout(escrow_id, amount_cents, seller_id).
KIFF gates each disbursement. DISBURSE_PAYOUT is allowed only while the escrow
is CLEARED; once the payout ships the escrow advances to DISBURSED, and KIFF
declines every further attempt. The boundary is what makes instant payouts
possible — you can ship the payout the moment state clears, without a manual
review gate, because KIFF holds the invariant that each escrow pays out once.

Built on Agno v2 (>=2.6). MODEL_PROVIDER = openai (default) | bedrock.
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
PAYOUT_APP_URL = os.environ.get("PAYOUT_APP_URL", "http://localhost:8082")


def _post(url, body):
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def make_model():
    provider = os.environ.get("MODEL_PROVIDER", "openai").lower()
    model_id = os.environ.get("MODEL_ID", "").strip()
    region = os.environ.get("AWS_REGION", "us-east-1")
    if provider == "bedrock":
        import boto3
        from agno.models.aws import AwsBedrock
        return AwsBedrock(id=model_id or "amazon.nova-pro-v1:0",
                          session=boto3.Session(region_name=region))
    from agno.models.openai import OpenAIChat
    return OpenAIChat(id=model_id or "gpt-4o-mini")


def build_guard() -> Guard:
    tool_map = ToolMap().bind(
        "disburse_payout",
        action="DISBURSE_PAYOUT",
        entity_type="Escrow",
        entity_arg="escrow_id",
    )
    client = HTTPClient(api_key="local", tool_map=tool_map, base_url=KIFF_BASE_URL)
    guard = Guard(client=client, tenant="cookbook", agent="payout-agent", mode="enforce")

    if KIFF_CLOUD_API_KEY:
        try:
            cloud_client = HTTPClient(
                api_key=KIFF_CLOUD_API_KEY, tool_map=tool_map, base_url=KIFF_CLOUD_URL,
            )
            cloud_guard = Guard(
                client=cloud_client, tenant="cloud", agent="payout-agent",
                mode="enforce", catalog=guard.catalog,
            )
            conn = cloud_guard.connect(
                adapter="agno", project="cookbook", environment="aws",
                workflow="instant-payout-enablement", sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def create_payout_agent(guard: Guard):
    from agno.agent import Agent
    from agno.tools import tool

    @tool
    def disburse_payout(escrow_id: str, amount_cents: int, seller_id: str) -> str:
        """Disburse the payout to a seller once escrow has cleared."""
        result = _post(f"{PAYOUT_APP_URL}/disburse", {
            "escrow_id": escrow_id,
            "amount_cents": amount_cents,
            "seller_id": seller_id,
        })
        return json.dumps(result)

    agent = Agent(
        model=make_model(),
        tools=[disburse_payout],
        tool_hooks=[agno_hook(guard)],
        instructions=[
            "You are a payout agent. When escrow clears, call disburse_payout "
            "with the escrow_id, amount_cents, and seller_id to ship the payout instantly.",
        ],
    )
    return agent


def run_agent(agent, message: str) -> str:
    response = agent.run(message)
    if hasattr(response, "content"):
        return response.content
    return str(response)
