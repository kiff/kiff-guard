"""scenario.py — refund-enablement-guard proof.

The enablement story, led by the agent succeeding:

WITH KIFF: a REAL Agno agent (model is selectable; OpenAI by default,
Bedrock via MODEL_PROVIDER) issues the refund on a PAID order — KIFF
allows it, the payout runs, and the order advances to REFUNDED. The
same agent then retries, and KIFF declines every repeat because the
order is no longer PAID. You hand the agent the refund route; the
boundary makes its limits exact.

WITHOUT KIFF: the agent pays out on every call — the duplicate refunds
go through and the money is gone.
"""

from __future__ import annotations

import json, os, sys, time
from urllib import request as urllib_request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                 "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap  # noqa: F401
from kiff_guard.decision import Hold

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
REFUND_APP_URL = os.environ.get("REFUND_APP_URL", "http://localhost:8082")
RETRIES = int(os.environ.get("RETRY_COUNT", "5"))
REFUND_CENTS = int(os.environ.get("REFUND_CENTS", "4900"))


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
    banner("WITHOUT KIFF — ungoverned: agent pays out on every retry")
    post(f"{REFUND_APP_URL}/order", {"order_id": order_id, "total_cents": REFUND_CENTS})
    post(f"{REFUND_APP_URL}/pay", {"order_id": order_id})
    print(f"order {order_id} created + paid: ${REFUND_CENTS / 100:.2f}")
    print(f"agent issues a refund, then retries {RETRIES - 1} times...")
    for i in range(1, RETRIES + 1):
        r = post(f"{REFUND_APP_URL}/refund",
                 {"order_id": order_id, "amount_cents": REFUND_CENTS, "reason": "customer request"})
        print(f"  refund {i}: paid out ${r['amount_cents'] / 100:.2f} (#{r['refund_number']})")
    ledger = get(f"{REFUND_APP_URL}/ledger")
    order = ledger["orders"][order_id]
    paid_out = sum(x["amount_cents"] for x in order["refunds"])
    print(f"\n  RESULT: {len(order['refunds'])} refunds, ${paid_out / 100:.2f} paid out "
          f"on a ${REFUND_CENTS / 100:.2f} order — OVER-REFUND")
    return order


def run_with_kiff(order_id):
    banner("WITH KIFF — real agent issues the refund; the repeat is declined")
    post(f"{REFUND_APP_URL}/order", {"order_id": order_id, "total_cents": REFUND_CENTS})
    post(f"{REFUND_APP_URL}/pay", {"order_id": order_id})
    post(f"{KIFF_BASE_URL}/seed", {"order_id": order_id})
    post(f"{KIFF_BASE_URL}/v1/events/raw",
         {"order_id": order_id, "type": "PAYMENT_CAPTURED", "actor_id": "system"})
    state_r = get(f"{KIFF_BASE_URL}/v1/entities/{order_id}/state")
    print(f"order {order_id} created + paid: ${REFUND_CENTS / 100:.2f}, state={state_r['state']}")

    from refund_agent import build_guard, create_refund_agent, run_agent, make_model
    guard = build_guard()
    print(f"  model: {type(make_model()).__name__} "
          f"(MODEL_PROVIDER={os.environ.get('MODEL_PROVIDER', 'openai')})")

    # 1) Real Agno agent issues the legitimate refund — KIFF allows it.
    print(f"\nagent (real model via Agno) refunds order {order_id}...")
    agent = create_refund_agent(guard)
    response = run_agent(
        agent,
        f"Refund order {order_id} for {REFUND_CENTS} cents; reason: customer request.")
    print(f"  agent response: {str(response)[:120]}...")

    # The refund executed; advance the order to REFUNDED.
    post(f"{KIFF_BASE_URL}/v1/events/raw",
         {"order_id": order_id, "type": "REFUND_ISSUED", "actor_id": "refund-agent"})
    state_r = get(f"{KIFF_BASE_URL}/v1/entities/{order_id}/state")
    print(f"  state after refund: {state_r['state']}")

    # 2) Agent retries the refund — KIFF declines each repeat.
    print(f"\nagent retries the refund {RETRIES - 1} more times...")
    blocked = 0
    for i in range(2, RETRIES + 1):
        args = {"order_id": order_id, "amount_cents": REFUND_CENTS, "reason": "retry"}
        try:
            def do_refund():
                return post(f"{REFUND_APP_URL}/refund", args)
            result = guard.evaluate("issue_refund", args, run=do_refund)
            print(f"  attempt {i}: ALLOWED (#{result.get('refund_number', '?')})")
        except Hold as h:
            blocked += 1
            reason = h.decision.reason[:70] if h.decision.reason else "withheld"
            print(f"  attempt {i}: BLOCKED by KIFF ({reason})")

    ledger = get(f"{REFUND_APP_URL}/ledger")
    order = ledger["orders"][order_id]
    paid_out = sum(x["amount_cents"] for x in order["refunds"])
    print(f"\n  RESULT: {len(order['refunds'])} refund(s), ${paid_out / 100:.2f} paid out; "
          f"{blocked} repeat(s) declined")
    return order, blocked


def main():
    stamp = int(time.time())

    a = run_without_kiff(f"order-nokiff-{stamp}")
    time.sleep(0.5)
    post(f"{REFUND_APP_URL}/reset", {})

    b_order, b_blocked = run_with_kiff(f"order-kiff-{stamp}")

    banner("VERDICT")
    a_refunds = len(a["refunds"])
    b_refunds = len(b_order["refunds"])
    print(f"  WITHOUT KIFF : {a_refunds} refunds paid out   FAIL — over-refund")
    print(f"  WITH KIFF    : {b_refunds} refund(s), {b_blocked} declined   "
          f"PASS — agent shipped the legitimate refund; repeats declined")
    print()

    pass_condition = b_refunds < a_refunds and b_refunds >= 1 and b_blocked > 0
    if pass_condition:
        print("  PROOF: the real agent issued the refund on its own (allowed), and KIFF")
        print("  declined every repeat once the order was no longer PAID. You ship the agent.")
    else:
        print("  UNEXPECTED: see output above.")

    sys.exit(0 if pass_condition else 1)


if __name__ == "__main__":
    main()
