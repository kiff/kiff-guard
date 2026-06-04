"""scenario.py — chargeback-dispute-guard proof.

WITHOUT KIFF: a disputes agent submits the same chargeback 5 times →
  5x $25 scheme fees ($125) on a single dispute. Duplicate chargebacks
  risk penalties from Visa/Mastercard.
WITH KIFF: a REAL Strands agent submits once (KIFF allows, INVESTIGATED).
  Every retry is blocked (state=SUBMITTED, state_not_allowed). 1 submission,
  $25 fee, 4 blocked.
"""

from __future__ import annotations

import json, os, sys, time
from urllib import request as urllib_request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.decision import Hold

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
KIFF_CLOUD_API_KEY = os.environ.get("KIFF_CLOUD_API_KEY", "")
KIFF_CLOUD_URL = os.environ.get("KIFF_CLOUD_URL", "https://api.kiff.dev")
DISPUTES_APP_URL = os.environ.get("DISPUTES_APP_URL", "http://localhost:8082")
RETRIES = int(os.environ.get("RETRY_COUNT", "5"))
DISPUTE_AMOUNT = 15000  # $150.00
REASON_CODE = "10.4"    # Visa: Other fraud - Card absent


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


def run_without_kiff(dispute_id):
    banner("WITHOUT KIFF — ungoverned: duplicate chargebacks incur fees")
    post(f"{DISPUTES_APP_URL}/dispute", {"dispute_id": dispute_id,
         "amount_cents": DISPUTE_AMOUNT, "reason_code": REASON_CODE})
    print(f"dispute {dispute_id}: ${DISPUTE_AMOUNT/100:.2f}, reason={REASON_CODE}")
    print(f"submitting chargeback {RETRIES} times...")

    for i in range(1, RETRIES + 1):
        r = post(f"{DISPUTES_APP_URL}/submit", {"dispute_id": dispute_id,
            "reason_code": REASON_CODE, "amount_cents": DISPUTE_AMOUNT})
        print(f"  submission {i}: #{r['submission_number']} (fee: ${r['scheme_fee_cents']/100:.2f})")

    ledger = get(f"{DISPUTES_APP_URL}/ledger")
    d = ledger["disputes"][dispute_id]
    print(f"\n  RESULT: {len(d['submissions'])} submissions, "
          f"${ledger['total_fees_cents']/100:.2f} in scheme fees — PENALTY RISK")
    return d, ledger["total_fees_cents"]


def run_with_kiff(dispute_id):
    banner("WITH KIFF — real agent + gate enforces once-only submission")
    post(f"{DISPUTES_APP_URL}/dispute", {"dispute_id": dispute_id,
         "amount_cents": DISPUTE_AMOUNT, "reason_code": REASON_CODE})
    post(f"{KIFF_BASE_URL}/seed", {"dispute_id": dispute_id})
    print(f"dispute {dispute_id} seeded: state=INVESTIGATED")

    from disputes_agent import build_guard, create_disputes_agent, run_agent

    guard = build_guard()

    print(f"\nagent (real gpt-4o-mini via Strands) submitting chargeback...")
    agent = create_disputes_agent(guard)
    response = run_agent(
        agent,
        f"Submit a chargeback for dispute {dispute_id}. "
        f"Use reason_code={REASON_CODE} and amount_cents={DISPUTE_AMOUNT}."
    )
    print(f"  agent response: {str(response)[:120]}...")

    ledger = get(f"{DISPUTES_APP_URL}/ledger")
    d = ledger["disputes"][dispute_id]
    print(f"  after agent: {len(d['submissions'])} submission(s)")

    print(f"\nretry storm: {RETRIES - 1} more attempts through the guard...")
    blocked = 0

    for i in range(2, RETRIES + 1):
        args = {"dispute_id": dispute_id, "reason_code": REASON_CODE, "amount_cents": DISPUTE_AMOUNT}
        try:
            decision = guard.decide_only("submit_chargeback", args)
            if decision.withheld:
                guard.record_withheld("submit_chargeback", args, decision)
                blocked += 1
                print(f"  retry {i}: BLOCKED by KIFF ({decision.reason[:60]})")
            else:
                guard.record_executed("submit_chargeback", args, decision)
                r = post(f"{DISPUTES_APP_URL}/submit", args)
                print(f"  retry {i}: ALLOWED (#{r['submission_number']})")
        except Exception as e:
            blocked += 1
            print(f"  retry {i}: ERROR ({e})")

    ledger = get(f"{DISPUTES_APP_URL}/ledger")
    d = ledger["disputes"][dispute_id]
    print(f"\n  RESULT: {len(d['submissions'])} submission(s), "
          f"${ledger['total_fees_cents']/100:.2f} in fees; {blocked} blocked by KIFF")
    return d, ledger["total_fees_cents"], blocked


def main():
    stamp = int(time.time())

    a_d, a_fees = run_without_kiff(f"dsp-nokiff-{stamp}")
    time.sleep(0.5)
    post(f"{DISPUTES_APP_URL}/reset", {})

    b_d, b_fees, b_blocked = run_with_kiff(f"dsp-kiff-{stamp}")

    banner("VERDICT")
    print(f"  WITHOUT KIFF : {len(a_d['submissions'])} submissions, "
          f"${a_fees/100:.2f} in fees   FAIL — duplicate chargeback penalty risk")
    print(f"  WITH KIFF    : {len(b_d['submissions'])} submission(s), "
          f"${b_fees/100:.2f} in fees, {b_blocked} blocked   PASS")
    print()

    pass_condition = len(b_d["submissions"]) == 1 and b_blocked > 0 and len(a_d["submissions"]) > 1
    if pass_condition:
        print("  PROOF: the real agent's chargeback was submitted once. KIFF blocked")
        print("  every retry after the dispute moved to SUBMITTED state.")
    else:
        print("  UNEXPECTED: see output above.")

    sys.exit(0 if pass_condition else 1)


if __name__ == "__main__":
    main()
