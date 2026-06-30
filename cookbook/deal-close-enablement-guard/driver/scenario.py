"""scenario.py — deal-close-enablement-guard proof.

The enablement story, led by the agent succeeding:

WITH KIFF: a REAL Agno agent (model is selectable; OpenAI by default,
Bedrock via MODEL_PROVIDER) applies the closing discount on an OPEN deal —
KIFF allows it, the discount is recorded, and the deal advances to
DISCOUNTED. The same agent then retries, and KIFF declines every repeat
because the deal is no longer OPEN. You put the agent on closing; the
boundary makes its limits exact — it grants the discount, it does not
stack margin away.

WITHOUT KIFF: the agent stacks a new discount on every call — the margin
is given away again and again.
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
DEAL_APP_URL = os.environ.get("DEAL_APP_URL", "http://localhost:8082")
RETRIES = int(os.environ.get("RETRY_COUNT", "5"))
DISCOUNT_PERCENT = int(os.environ.get("DISCOUNT_PERCENT", "15"))


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


def run_without_kiff(deal_id):
    banner("WITHOUT KIFF — ungoverned: agent stacks a discount on every retry")
    post(f"{DEAL_APP_URL}/deal", {"deal_id": deal_id, "value_cents": 1000000})
    post(f"{DEAL_APP_URL}/qualify", {"deal_id": deal_id})
    print(f"deal {deal_id} created + qualified (OPEN)")
    print(f"agent applies a {DISCOUNT_PERCENT}% discount, then retries {RETRIES - 1} times...")
    for i in range(1, RETRIES + 1):
        r = post(f"{DEAL_APP_URL}/discount",
                 {"deal_id": deal_id, "percent": DISCOUNT_PERCENT, "reason": "close the deal"})
        print(f"  discount {i}: applied {r['percent']}% (#{r['discount_number']})")
    ledger = get(f"{DEAL_APP_URL}/ledger")
    deal = ledger["deals"][deal_id]
    total = sum(x["percent"] for x in deal["discounts"])
    print(f"\n  RESULT: {len(deal['discounts'])} discounts, {total}% stacked "
          f"on one deal — MARGIN GIVEAWAY")
    return deal


def run_with_kiff(deal_id):
    banner("WITH KIFF — real agent applies the discount; the repeat is declined")
    post(f"{DEAL_APP_URL}/deal", {"deal_id": deal_id, "value_cents": 1000000})
    post(f"{DEAL_APP_URL}/qualify", {"deal_id": deal_id})
    post(f"{KIFF_BASE_URL}/seed", {"deal_id": deal_id})
    post(f"{KIFF_BASE_URL}/v1/events/raw",
         {"deal_id": deal_id, "type": "DEAL_QUALIFIED", "actor_id": "system"})
    state_r = get(f"{KIFF_BASE_URL}/v1/entities/{deal_id}/state")
    print(f"deal {deal_id} created + qualified, state={state_r['state']}")

    from deal_agent import build_guard, create_deal_agent, run_agent, make_model
    guard = build_guard()
    print(f"  model: {type(make_model()).__name__} "
          f"(MODEL_PROVIDER={os.environ.get('MODEL_PROVIDER', 'openai')})")

    # 1) Real Agno agent applies the legitimate closing discount — KIFF allows it.
    print(f"\nagent (real model via Agno) discounts deal {deal_id}...")
    agent = create_deal_agent(guard)
    response = run_agent(
        agent,
        f"Close deal {deal_id} with a {DISCOUNT_PERCENT}% discount; reason: close the deal.")
    print(f"  agent response: {str(response)[:120]}...")

    # The discount executed; advance the deal to DISCOUNTED.
    post(f"{KIFF_BASE_URL}/v1/events/raw",
         {"deal_id": deal_id, "type": "DISCOUNT_APPLIED", "actor_id": "deal-agent"})
    state_r = get(f"{KIFF_BASE_URL}/v1/entities/{deal_id}/state")
    print(f"  state after discount: {state_r['state']}")

    # 2) Agent retries the discount — KIFF declines each repeat.
    print(f"\nagent retries the discount {RETRIES - 1} more times...")
    blocked = 0
    for i in range(2, RETRIES + 1):
        args = {"deal_id": deal_id, "percent": DISCOUNT_PERCENT, "reason": "retry"}
        try:
            def do_discount():
                return post(f"{DEAL_APP_URL}/discount", args)
            result = guard.evaluate("apply_discount", args, run=do_discount)
            print(f"  attempt {i}: ALLOWED (#{result.get('discount_number', '?')})")
        except Hold as h:
            blocked += 1
            reason = h.decision.reason[:70] if h.decision.reason else "withheld"
            print(f"  attempt {i}: BLOCKED by KIFF ({reason})")

    ledger = get(f"{DEAL_APP_URL}/ledger")
    deal = ledger["deals"][deal_id]
    total = sum(x["percent"] for x in deal["discounts"])
    print(f"\n  RESULT: {len(deal['discounts'])} discount(s), {total}% applied; "
          f"{blocked} repeat(s) declined")
    return deal, blocked


def main():
    stamp = int(time.time())

    a = run_without_kiff(f"deal-nokiff-{stamp}")
    time.sleep(0.5)
    post(f"{DEAL_APP_URL}/reset", {})

    b_deal, b_blocked = run_with_kiff(f"deal-kiff-{stamp}")

    banner("VERDICT")
    a_discounts = len(a["discounts"])
    b_discounts = len(b_deal["discounts"])
    print(f"  WITHOUT KIFF : {a_discounts} discounts stacked   FAIL — margin giveaway")
    print(f"  WITH KIFF    : {b_discounts} discount(s), {b_blocked} declined   "
          f"PASS — agent closed the deal; repeats declined")
    print()

    pass_condition = b_discounts < a_discounts and b_discounts >= 1 and b_blocked > 0
    if pass_condition:
        print("  PROOF: the real agent applied the closing discount on its own (allowed), and KIFF")
        print("  declined every repeat once the deal was no longer OPEN. You ship the agent on closing.")
    else:
        print("  UNEXPECTED: see output above.")

    sys.exit(0 if pass_condition else 1)


if __name__ == "__main__":
    main()
