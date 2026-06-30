"""payment_agent — Agno (v2) agent with the KIFF guard via agno_hook.

The agent has one tool: retry_payment(invoice_id, amount_cents, reason).
KIFF gates each retry. RETRY_PAYMENT is allowed only while the invoice is
PAST_DUE; once the charge recovers it the invoice advances to RECOVERED,
and KIFF declines — the agent cannot keep hitting the card. The boundary is
what lets you put the agent on payment recovery at all: it charges once to
recover, it does not hammer the card.

Built on Agno v2 (>=2.6). Model is selectable: MODEL_PROVIDER = openai
(default) | bedrock. The KIFF tool hook is model-agnostic.

Environment:
  MODEL_PROVIDER, MODEL_ID, OPENAI_API_KEY (openai),
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION (bedrock),
  KIFF_BASE_URL, KIFF_CLOUD_API_KEY, KIFF_CLOUD_URL, PAYMENT_APP_URL
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
PAYMENT_APP_URL = os.environ.get("PAYMENT_APP_URL", "http://localhost:8082")


def _post(url, body):
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def make_model():
    """Pick the model from env. OpenAI (default, no AWS) and Bedrock are
    interchangeable; the guard hook does not care which model proposes the
    tool call. For Bedrock-hosted Claude, set MODEL_PROVIDER=bedrock and
    MODEL_ID to a us.anthropic.claude-* id."""
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
        "retry_payment",
        action="RETRY_PAYMENT",
        entity_type="Invoice",
        entity_arg="invoice_id",
    )
    client = HTTPClient(api_key="local", tool_map=tool_map, base_url=KIFF_BASE_URL)
    guard = Guard(client=client, tenant="cookbook", agent="dunning-agent", mode="enforce")

    if KIFF_CLOUD_API_KEY:
        try:
            cloud_client = HTTPClient(
                api_key=KIFF_CLOUD_API_KEY, tool_map=tool_map, base_url=KIFF_CLOUD_URL,
            )
            cloud_guard = Guard(
                client=cloud_client, tenant="cloud", agent="dunning-agent",
                mode="enforce", catalog=guard.catalog,
            )
            conn = cloud_guard.connect(
                adapter="agno", project="cookbook", environment="aws",
                workflow="payment-recovery-enablement", sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def create_payment_agent(guard: Guard):
    """Create an Agno agent with the guarded retry_payment tool."""
    from agno.agent import Agent
    from agno.tools import tool

    @tool
    def retry_payment(invoice_id: str, amount_cents: int, reason: str) -> str:
        """Retry the charge on a past-due invoice. amount_cents is the amount to recover."""
        result = _post(f"{PAYMENT_APP_URL}/charge", {
            "invoice_id": invoice_id,
            "amount_cents": amount_cents,
            "reason": reason,
        })
        return json.dumps(result)

    agent = Agent(
        model=make_model(),
        tools=[retry_payment],
        tool_hooks=[agno_hook(guard)],
        instructions=[
            "You are a payment-recovery agent. When asked to recover a past-due "
            "invoice, call retry_payment with the invoice_id, amount_cents, and a brief reason.",
        ],
    )
    return agent


def run_agent(agent, message: str) -> str:
    response = agent.run(message)
    if hasattr(response, "content"):
        return response.content
    return str(response)
