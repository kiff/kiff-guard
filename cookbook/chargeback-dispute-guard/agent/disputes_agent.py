"""disputes_agent — Strands agent with KIFF guard via kiff_hook_provider.

Strands vote-shape: kiff_hook_provider registers BeforeToolCallEvent.
Before each tool runs, KIFF decides. If blocked, Strands cancels the tool.

Environment: OPENAI_API_KEY, KIFF_BASE_URL, KIFF_CLOUD_API_KEY, KIFF_CLOUD_URL, DISPUTES_APP_URL
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.adapters.strands import kiff_hook_provider

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
KIFF_CLOUD_API_KEY = os.environ.get("KIFF_CLOUD_API_KEY", "")
KIFF_CLOUD_URL = os.environ.get("KIFF_CLOUD_URL", "https://api.kiff.dev")
DISPUTES_APP_URL = os.environ.get("DISPUTES_APP_URL", "http://localhost:8082")


def _post(url, body):
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def build_guard() -> Guard:
    tool_map = ToolMap().bind(
        "submit_chargeback",
        action="SUBMIT_CHARGEBACK",
        entity_type="Dispute",
        entity_arg="dispute_id",
    )
    client = HTTPClient(api_key="local", tool_map=tool_map, base_url=KIFF_BASE_URL)
    guard = Guard(client=client, tenant="cookbook", agent="disputes-agent", mode="enforce")

    if KIFF_CLOUD_API_KEY:
        try:
            cloud_client = HTTPClient(
                api_key=KIFF_CLOUD_API_KEY, tool_map=tool_map, base_url=KIFF_CLOUD_URL,
            )
            conn = cloud_client.connect_guard(
                agent_id="disputes-agent", adapter="strands", mode="enforce",
                project="cookbook", environment="aws", workflow="chargeback-dispute",
                sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def create_disputes_agent(guard: Guard):
    from strands import Agent, tool
    from strands.models.openai import OpenAIModel

    @tool
    def submit_chargeback(dispute_id: str, reason_code: str, amount_cents: int) -> str:
        """Submit a chargeback to the card scheme for a dispute."""
        result = _post(f"{DISPUTES_APP_URL}/submit", {
            "dispute_id": dispute_id,
            "reason_code": reason_code,
            "amount_cents": amount_cents,
        })
        # Advance state after real submission
        _post(f"{KIFF_BASE_URL}/v1/events/raw", {
            "dispute_id": dispute_id,
            "type": "CHARGEBACK_SUBMITTED",
            "actor_id": "disputes-agent",
            "payload": {"reason_code": reason_code, "amount_cents": amount_cents},
        })
        return json.dumps(result)

    model = OpenAIModel(model_id="gpt-4o-mini")
    agent = Agent(
        model=model,
        tools=[submit_chargeback],
        hooks=[kiff_hook_provider(guard)],
        system_prompt=(
            "You are a disputes agent. When asked to submit a chargeback, "
            "call submit_chargeback with the dispute_id, reason_code, and amount_cents."
        ),
    )
    return agent


def run_agent(agent, message: str) -> str:
    response = agent(message)
    if hasattr(response, "message"):
        return str(response.message.get("content", ""))
    return str(response)
