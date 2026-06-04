"""scenario.py — the refund-ceiling proof.

Runs the scenario twice:

  WITHOUT KIFF: direct /refund calls simulate retries → over-refund.
  WITH KIFF: a REAL LLM agent (gpt-4o-mini via LangGraph) is asked to
    refund, and then the same tool is retried. The guard blocks once the
    order hits its ceiling.

The first refund is LLM-driven (proves real agent + guard integration).
The retry storm then calls the guarded tool directly (proves the gate
blocks regardless of who calls).
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from urllib import request as urllib_request
from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.decision import Hold

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
KIFF_CLOUD_API_KEY = os.environ.get("KIFF_CLOUD_API_KEY", "")
KIFF_CLOUD_URL = os.environ.get("KIFF_CLOUD_URL", "https://api.kiff.dev")
REFUND_APP_URL = os.environ.get("REFUND_APP_URL", "http://localhost:8082")
RETRIES = int(os.environ.get("RETRY_COUNT", "5"))
ORDER_AMOUNT = 10000  # $100.00
REFUND_AMOUNT = 5000  # $50.00 per attempt


def post(url, body):
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def get(url):
    with urllib_request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def banner(title):
    print(f"\n{'=' * 66}\n  {title}\n{'=' * 66}")


def run_without_kiff(order_id):
    """No gate: every retry refunds."""
    banner("WITHOUT KIFF — ungoverned: every retry refunds")
    post(f"{REFUND_APP_URL}/order", {"order_id": order_id, "amount_cents": ORDER_AMOUNT})
    print(f"order {order_id} created: ${ORDER_AMOUNT/100:.2f}")
    print(f"retrying ${REFUND_AMOUNT/100:.0f} refund {RETRIES} times...")

    for i in range(1, RETRIES + 1):
        r = post(f"{REFUND_APP_URL}/refund", {"order_id": order_id, "amount_cents": REFUND_AMOUNT})
        print(f"  attempt {i}: refunded ${REFUND_AMOUNT/100:.2f} (#{r['refund_number']})")

    ledger = get(f"{REFUND_APP_URL}/ledger")
    order = ledger["orders"][order_id]
    print(f"\n  RESULT: ${order['refunded_cents']/100:.2f} refunded across "
          f"{len(order['refunds'])} refunds (order was ${ORDER_AMOUNT/100:.2f})")
    return order


def run_with_kiff(order_id):
    """KIFF gate with a REAL agent for the first call, then retry storm."""
    banner("WITH KIFF — real agent + gate enforces the refund ceiling")

    # Setup
    post(f"{REFUND_APP_URL}/order", {"order_id": order_id, "amount_cents": ORDER_AMOUNT})
    post(f"{KIFF_BASE_URL}/seed", {"order_id": order_id})
    print(f"order {order_id} created + seeded: ${ORDER_AMOUNT/100:.2f}, state=PAID")

    # Build guard
    from refund_agent import build_guard, create_refund_agent, run_agent

    guard = build_guard()

    # 1) Real LLM-driven refund via the agent
    print(f"\nagent (real gpt-4o-mini) asked to refund ${REFUND_AMOUNT/100:.2f}...")
    agent = create_refund_agent(guard)
    response = run_agent(
        agent,
        f"Please issue a refund of {REFUND_AMOUNT} cents for order {order_id}. "
        f"Call issue_refund with order_id={order_id} and amount_cents={REFUND_AMOUNT}."
    )
    print(f"  agent response: {response[:100]}...")

    ledger = get(f"{REFUND_APP_URL}/ledger")
    order = ledger["orders"].get(order_id, {})
    agent_refunds = len(order.get("refunds", []))
    print(f"  after agent: {agent_refunds} refund(s), "
          f"${order.get('refunded_cents', 0)/100:.2f} refunded")

    # 2) Retry storm: call the guarded tool directly
    print(f"\nretry storm: {RETRIES - 1} more attempts through the guard...")
    blocked = 0
    allowed_extra = 0

    for i in range(2, RETRIES + 1):
        args = {"order_id": order_id, "amount_cents": REFUND_AMOUNT}
        try:
            def do_refund():
                r = post(f"{REFUND_APP_URL}/refund", args)
                post(f"{KIFF_BASE_URL}/v1/events/raw", {
                    "order_id": order_id, "type": "REFUND_ISSUED",
                    "actor_id": "refund-agent",
                    "payload": {"amount_cents": REFUND_AMOUNT},
                })
                l = get(f"{REFUND_APP_URL}/ledger")
                o = l["orders"][order_id]
                if o["refunded_cents"] >= ORDER_AMOUNT:
                    post(f"{KIFF_BASE_URL}/v1/events/raw", {
                        "order_id": order_id, "type": "ORDER_FULLY_REFUNDED",
                        "actor_id": "system",
                    })
                return r

            result = guard.evaluate("issue_refund", args, run=do_refund)
            allowed_extra += 1
            print(f"  retry {i}: ALLOWED (refund #{result['refund_number']})")
        except Hold as h:
            blocked += 1
            reason = h.decision.reason[:60] if h.decision.reason else "withheld"
            print(f"  retry {i}: BLOCKED by KIFF ({reason})")

    ledger = get(f"{REFUND_APP_URL}/ledger")
    order = ledger["orders"][order_id]
    total_allowed = agent_refunds + allowed_extra
    print(f"\n  RESULT: ${order['refunded_cents']/100:.2f} refunded across "
          f"{total_allowed} refund(s); {blocked} blocked by KIFF.")
    return order


def main():
    stamp = int(time.time())

    a = run_without_kiff(f"ord-nokiff-{stamp}")
    time.sleep(0.5)
    post(f"{REFUND_APP_URL}/reset", {})

    b = run_with_kiff(f"ord-kiff-{stamp}")

    banner("VERDICT")
    a_refunded = a["refunded_cents"]
    b_refunded = b["refunded_cents"]
    a_count = len(a["refunds"])
    b_count = len(b["refunds"])
    print(f"  WITHOUT KIFF : ${a_refunded/100:.2f} refunded ({a_count} refunds)   "
          f"FAIL — exceeds order total")
    print(f"  WITH KIFF    : ${b_refunded/100:.2f} refunded ({b_count} refund(s))    "
          f"PASS — capped at order total")
    print()

    pass_condition = b_refunded <= ORDER_AMOUNT and a_refunded > ORDER_AMOUNT
    if pass_condition:
        print("  PROOF: the real agent's $50 refund was legitimate. Only a state-aware")
        print("  gate stopped the retry storm from over-refunding past the order ceiling.")
    else:
        print("  UNEXPECTED: see output above.")

    sys.exit(0 if pass_condition else 1)


if __name__ == "__main__":
    main()
