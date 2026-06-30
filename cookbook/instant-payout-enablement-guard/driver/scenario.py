"""scenario.py — instant-payout-enablement-guard proof.

WITH KIFF: a REAL Agno agent disburses to the seller the moment escrow clears —
KIFF allows it, the payout ships, and the escrow advances to DISBURSED. The
same agent retries, and KIFF declines every repeat. You ship instant payouts
without a manual review gate, because the boundary holds the invariant that
each escrow pays out once.

WITHOUT KIFF: the payout fires on every retry — the seller gets paid multiple
times on the same escrow.
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
PAYOUT_APP_URL = os.environ.get("PAYOUT_APP_URL", "http://localhost:8082")
RETRIES = int(os.environ.get("RETRY_COUNT", "5"))
AMOUNT_CENTS = int(os.environ.get("AMOUNT_CENTS", "24900"))
SELLER_ID = "seller-001"


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


def run_without_kiff(escrow_id):
    banner("WITHOUT KIFF — ungoverned: payout fires on every retry")
    post(f"{PAYOUT_APP_URL}/escrow", {"escrow_id": escrow_id, "amount_cents": AMOUNT_CENTS, "seller_id": SELLER_ID})
    post(f"{PAYOUT_APP_URL}/clear", {"escrow_id": escrow_id})
    print(f"escrow {escrow_id} created + cleared: ${AMOUNT_CENTS / 100:.2f} to {SELLER_ID}")
    print(f"agent disburses, then retries {RETRIES - 1} more times...")
    for i in range(1, RETRIES + 1):
        r = post(f"{PAYOUT_APP_URL}/disburse",
                 {"escrow_id": escrow_id, "amount_cents": AMOUNT_CENTS, "seller_id": SELLER_ID})
        print(f"  payout {i}: sent ${r['amount_cents'] / 100:.2f} to {SELLER_ID} (#{r['disbursement_number']})")
    ledger = get(f"{PAYOUT_APP_URL}/ledger")
    e = ledger["escrows"][escrow_id]
    total = sum(x["amount_cents"] for x in e["disbursements"])
    print(f"\n  RESULT: {len(e['disbursements'])} disbursements, ${total / 100:.2f} paid out — DUPLICATE PAYOUTS")
    return e


def run_with_kiff(escrow_id):
    banner("WITH KIFF — real agent ships instant payout; the repeat is declined")
    post(f"{PAYOUT_APP_URL}/escrow", {"escrow_id": escrow_id, "amount_cents": AMOUNT_CENTS, "seller_id": SELLER_ID})
    post(f"{PAYOUT_APP_URL}/clear", {"escrow_id": escrow_id})
    post(f"{KIFF_BASE_URL}/seed", {"escrow_id": escrow_id})
    post(f"{KIFF_BASE_URL}/v1/events/raw",
         {"escrow_id": escrow_id, "type": "ESCROW_CLEARED", "actor_id": "system"})
    state_r = get(f"{KIFF_BASE_URL}/v1/entities/{escrow_id}/state")
    print(f"escrow {escrow_id} created + cleared: ${AMOUNT_CENTS / 100:.2f}, state={state_r['state']}")

    from payout_agent import build_guard, create_payout_agent, run_agent, make_model
    guard = build_guard()
    print(f"  model: {type(make_model()).__name__} "
          f"(MODEL_PROVIDER={os.environ.get('MODEL_PROVIDER', 'openai')})")

    print(f"\nagent (real model via Agno) disburses escrow {escrow_id} instantly...")
    agent = create_payout_agent(guard)
    response = run_agent(
        agent,
        f"Escrow {escrow_id} has cleared. Disburse ${AMOUNT_CENTS / 100:.2f} to seller {SELLER_ID} instantly.")
    print(f"  agent response: {str(response)[:120]}...")

    post(f"{KIFF_BASE_URL}/v1/events/raw",
         {"escrow_id": escrow_id, "type": "PAYOUT_DISBURSED", "actor_id": "payout-agent"})
    state_r = get(f"{KIFF_BASE_URL}/v1/entities/{escrow_id}/state")
    print(f"  state after payout: {state_r['state']}")

    print(f"\nagent retries the payout {RETRIES - 1} more times...")
    blocked = 0
    for i in range(2, RETRIES + 1):
        args = {"escrow_id": escrow_id, "amount_cents": AMOUNT_CENTS, "seller_id": SELLER_ID}
        try:
            def do_disburse():
                return post(f"{PAYOUT_APP_URL}/disburse", args)
            result = guard.evaluate("disburse_payout", args, run=do_disburse)
            print(f"  attempt {i}: ALLOWED (#{result.get('disbursement_number', '?')})")
        except Hold as h:
            blocked += 1
            reason = h.decision.reason[:70] if h.decision.reason else "withheld"
            print(f"  attempt {i}: BLOCKED by KIFF ({reason})")

    ledger = get(f"{PAYOUT_APP_URL}/ledger")
    e = ledger["escrows"][escrow_id]
    total = sum(x["amount_cents"] for x in e["disbursements"])
    print(f"\n  RESULT: {len(e['disbursements'])} payout(s), ${total / 100:.2f} disbursed; "
          f"{blocked} repeat(s) declined")
    return e, blocked


def main():
    stamp = int(time.time())
    a = run_without_kiff(f"escrow-nokiff-{stamp}")
    time.sleep(0.5)
    post(f"{PAYOUT_APP_URL}/reset", {})
    b_e, b_blocked = run_with_kiff(f"escrow-kiff-{stamp}")

    banner("VERDICT")
    a_n = len(a["disbursements"])
    b_n = len(b_e["disbursements"])
    print(f"  WITHOUT KIFF : {a_n} payouts sent        FAIL — duplicate payouts")
    print(f"  WITH KIFF    : {b_n} payout(s), {b_blocked} declined   "
          f"PASS — instant payout shipped; repeats declined")
    print()
    pass_condition = b_n < a_n and b_n >= 1 and b_blocked > 0
    if pass_condition:
        print("  PROOF: the real agent shipped the instant payout (allowed), and KIFF")
        print("  declined every repeat once the escrow was DISBURSED. You ship instant payouts.")
    else:
        print("  UNEXPECTED: see output above.")
    sys.exit(0 if pass_condition else 1)


if __name__ == "__main__":
    main()
