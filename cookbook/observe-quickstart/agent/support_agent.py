"""support_agent — an Agno agent wired to a KIFF guard in OBSERVE mode.

This is the zero-config on-ramp: the guard runs in `observe` mode, so it
records an audit trail and learns the action catalog WITHOUT a KIFF
account, a tenant, a domain, a kiff-decide gate, or any API call to KIFF.
It never blocks a tool.

    guard = Guard(mode="observe")     # no client, no tenant
    agent = Agent(..., tool_hooks=[agno_hook(guard)])

The same one-line integration that would govern the agent in enforce mode
also derives a starter domain from real traffic (see the driver, which
prints guard.receipts and export_yaml(guard.catalog)).

Environment: OPENAI_API_KEY is only needed for the live-agent path; the
driver's default offline path needs no keys at all.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard
from kiff_guard.adapters.agno import agno_hook


def build_guard() -> Guard:
    """A zero-config observe-mode guard: no client, no tenant, no cloud.

    This is the whole point of observe mode — it is decide-independent, so
    a brand-new user sees their own agent's behaviour in minutes with no
    KIFF account and nothing to configure."""
    return Guard(mode="observe", agent="support-agent")


def create_support_agent(guard: Guard):
    """A support agent with three tools, each gated by the observe-mode
    guard via agno_hook. In observe mode every tool runs and is recorded."""
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.tools import tool

    @tool
    def refund_order(order_id: str, amount_cents: int, reason: str) -> str:
        """Issue a refund on an order."""
        return json.dumps({"order_id": order_id, "refunded_cents": amount_cents, "reason": reason})

    @tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to a customer."""
        return json.dumps({"to": to, "subject": subject, "sent": True})

    @tool
    def escalate_ticket(ticket_id: str, priority: str) -> str:
        """Escalate a support ticket to a human."""
        return json.dumps({"ticket_id": ticket_id, "priority": priority, "escalated": True})

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[refund_order, send_email, escalate_ticket],
        tool_hooks=[agno_hook(guard)],
        instructions=[
            "You are a customer support agent. Use the tools to resolve the "
            "request: refund_order for refunds, send_email to notify the "
            "customer, escalate_ticket for anything you cannot resolve.",
        ],
    )
    return agent


# The scripted transcript the driver replays when no live agent is run.
# Each entry is one tool call (name, kwargs) — exactly the shape a real
# agent would produce. Replaying it through agno_hook(guard) exercises the
# real observe path with no LLM and no network.
SCRIPTED_CALLS = [
    ("refund_order", {"order_id": "ord_1001", "amount_cents": 2500, "reason": "damaged item"}),
    ("send_email", {"to": "alice@example.com", "subject": "Your refund", "body": "Processed."}),
    ("refund_order", {"order_id": "ord_1002", "amount_cents": 999, "reason": "late delivery"}),
    ("escalate_ticket", {"ticket_id": "tkt_77", "priority": "high"}),
    ("send_email", {"to": "bob@example.com", "subject": "Update", "body": "We're on it."}),
]
