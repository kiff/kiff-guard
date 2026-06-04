"""collections_agent — Agno agent with KIFF guard via agno_hook.

The agent has one tool: contact_borrower(case_id, channel, message).
KIFF gates each contact attempt. If a promise is active (PROMISE_ACTIVE),
KIFF blocks and the agent cannot contact the borrower.

Environment:
  OPENAI_API_KEY, KIFF_BASE_URL, KIFF_CLOUD_API_KEY, KIFF_CLOUD_URL, COLLECTIONS_APP_URL
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
COLLECTIONS_APP_URL = os.environ.get("COLLECTIONS_APP_URL", "http://localhost:8082")


def _post(url, body):
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _get(url):
    from urllib import request as urllib_request
    with urllib_request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def build_guard() -> Guard:
    tool_map = ToolMap().bind(
        "contact_borrower",
        action="INITIATE_COLLECTIONS_CONTACT",
        entity_type="CollectionsCase",
        entity_arg="case_id",
    )
    client = HTTPClient(api_key="local", tool_map=tool_map, base_url=KIFF_BASE_URL)
    guard = Guard(client=client, tenant="cookbook", agent="collections-agent", mode="enforce")

    if KIFF_CLOUD_API_KEY:
        try:
            cloud_client = HTTPClient(
                api_key=KIFF_CLOUD_API_KEY, tool_map=tool_map, base_url=KIFF_CLOUD_URL,
            )
            conn = cloud_client.connect_guard(
                agent_id="collections-agent", adapter="agno", mode="enforce",
                project="cookbook", environment="aws", workflow="collections-promise",
                sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def create_collections_agent(guard: Guard):
    """Create an Agno agent with the guarded contact_borrower tool."""
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.tools import tool

    @tool
    def contact_borrower(case_id: str, channel: str, message: str) -> str:
        """Contact a borrower via the specified channel (sms/email/voice)."""
        result = _post(f"{COLLECTIONS_APP_URL}/contact", {
            "case_id": case_id,
            "channel": channel,
        })
        # After a real contact that captures a promise, emit PROMISE_MADE
        # (in a real system the agent would parse the response and decide)
        return json.dumps(result)

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[contact_borrower],
        tool_hooks=[agno_hook(guard)],
        instructions=[
            "You are a collections agent. When asked to contact a borrower, "
            "call contact_borrower with the case_id, channel, and a brief message.",
        ],
    )
    return agent


def run_agent(agent, message: str) -> str:
    response = agent.run(message)
    if hasattr(response, "content"):
        return response.content
    return str(response)
