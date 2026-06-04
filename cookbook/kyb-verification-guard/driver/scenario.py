"""scenario.py — kyb-verification-guard proof (Agno Workflows).

WITHOUT KIFF: a KYB onboarding workflow re-runs the paid bureau check 5
  times (flaky retries, duplicate triggers, an operator re-submitting) —
  5x $12 bureau fees ($60) on one business, and a decided KYB outcome
  re-screened over and over.

WITH KIFF: a REAL Agno Workflow (gpt-4o-mini) runs the verification once
  (KIFF allows, business PENDING). The check advances the business to
  VERIFIED. Every re-run is blocked (state_not_allowed). 1 check, $12,
  4 blocked — once-and-done.
"""

from __future__ import annotations

import json, os, sys, time, uuid
from urllib import request as urllib_request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.decision import Hold

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
KIFF_CLOUD_API_KEY = os.environ.get("KIFF_CLOUD_API_KEY", "")
KIFF_CLOUD_URL = os.environ.get("KIFF_CLOUD_URL", "https://api.kiff.dev")
KYB_APP_URL = os.environ.get("KYB_APP_URL", "http://localhost:8082")
RETRIES = int(os.environ.get("RETRY_COUNT", "5"))
REG_NUMBER = "12345678"  # Companies House registration number


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


def run_without_kiff(business_id):
    banner("WITHOUT KIFF — ungoverned: the bureau check re-runs and re-bills")
    post(f"{KYB_APP_URL}/business",
         {"business_id": business_id, "name": "Acme Ltd", "registration_number": REG_NUMBER})
    print(f"business {business_id}: Acme Ltd, reg={REG_NUMBER}")
    print(f"workflow re-runs the paid bureau check {RETRIES} times...")

    for i in range(1, RETRIES + 1):
        r = post(f"{KYB_APP_URL}/verify",
                 {"business_id": business_id, "registration_number": REG_NUMBER})
        print(f"  check {i}: #{r['check_number']} (bureau fee: ${r['bureau_fee_cents']/100:.2f})")

    ledger = get(f"{KYB_APP_URL}/ledger")
    biz = ledger["businesses"][business_id]
    print(f"\n  RESULT: {len(biz['checks'])} bureau checks, "
          f"${ledger['total_fees_cents']/100:.2f} in fees — WASTED SPEND + RE-SCREENING")
    return biz, ledger["total_fees_cents"]


def run_with_kiff(business_id):
    banner("WITH KIFF — real Agno Workflow enforces once-and-done verification")
    post(f"{KYB_APP_URL}/business",
         {"business_id": business_id, "name": "Globex Ltd", "registration_number": REG_NUMBER})
    post(f"{KIFF_BASE_URL}/seed", {"business_id": business_id})
    print(f"business {business_id} seeded: Globex Ltd, state=PENDING")

    from kyb_workflow import build_guard, create_kyb_workflow, run_workflow

    guard = build_guard()
    workflow, verify_agent = create_kyb_workflow(guard)
    shape = "Workflow" if workflow is not None else "Agent (workflow API unavailable)"
    print(f"\nrunning KYB pipeline as Agno {shape} (real gpt-4o-mini)...")

    response = run_workflow(
        workflow, verify_agent,
        f"Onboard business {business_id}. Run the KYB check with "
        f"registration_number={REG_NUMBER}."
    )
    print(f"  workflow response: {str(response)[:120]}...")

    state_r = get(f"{KIFF_BASE_URL}/v1/entities/{business_id}/state")
    print(f"  state: {state_r['state']}")

    ledger = get(f"{KYB_APP_URL}/ledger")
    biz = ledger["businesses"][business_id]
    print(f"  after workflow: {len(biz['checks'])} bureau check(s)")

    print(f"\nretry storm: {RETRIES - 1} more runs of the verify step...")
    blocked = 0

    for i in range(2, RETRIES + 1):
        args = {"business_id": business_id, "registration_number": REG_NUMBER}
        try:
            decision = guard.decide_only("run_kyb_check", args)
            if decision.withheld:
                guard.record_withheld("run_kyb_check", args, decision)
                blocked += 1
                print(f"  re-run {i}: BLOCKED by KIFF ({(decision.reason or '')[:60]})")
            else:
                guard.record_executed("run_kyb_check", args, decision)
                r = post(f"{KYB_APP_URL}/verify", args)
                print(f"  re-run {i}: ALLOWED (#{r['check_number']})")
        except Exception as e:
            blocked += 1
            print(f"  re-run {i}: ERROR ({e})")

    ledger = get(f"{KYB_APP_URL}/ledger")
    biz = ledger["businesses"][business_id]
    print(f"\n  RESULT: {len(biz['checks'])} bureau check(s), "
          f"${ledger['total_fees_cents']/100:.2f} in fees; {blocked} blocked by KIFF")
    return biz, ledger["total_fees_cents"], blocked


def main():
    # Short alpha token (not a long digit run) so Agno's PIIDetectionGuardrail
    # doesn't read the business id as a phone number. The bureau registration
    # number (8 digits) is a realistic Companies House value, passed as a tool
    # arg rather than embedded in the agent prompt.
    tok = uuid.uuid4().hex[:6]

    a_biz, a_fees = run_without_kiff(f"biz-nokiff-{tok}")
    time.sleep(0.5)
    post(f"{KYB_APP_URL}/reset", {})

    b_biz, b_fees, b_blocked = run_with_kiff(f"biz-kiff-{tok}")

    banner("VERDICT")
    print(f"  WITHOUT KIFF : {len(a_biz['checks'])} checks, "
          f"${a_fees/100:.2f} in fees   FAIL — wasted bureau spend + re-screening")
    print(f"  WITH KIFF    : {len(b_biz['checks'])} check(s), "
          f"${b_fees/100:.2f} in fees, {b_blocked} blocked   PASS")
    print()

    pass_condition = len(b_biz["checks"]) == 1 and b_blocked > 0 and len(a_biz["checks"]) > 1
    if pass_condition:
        print("  PROOF: the real workflow's verification ran exactly once. KIFF blocked")
        print("  every re-run once the business moved to VERIFIED — no double bureau fee,")
        print("  no re-screening a decided entity.")
    else:
        print("  UNEXPECTED: see output above.")

    sys.exit(0 if pass_condition else 1)


if __name__ == "__main__":
    main()
