# kyb-verification-guard

A cookbook recipe proving KIFF makes a paid KYB verification step run
**exactly once** inside a structured agent **workflow** — no double bureau
fee, no re-screening a decided entity, even when the workflow retries or
re-enters.

**Adapter**: Agno (`tool_hooks` middleware shape) — using **Agno Workflows**

## The scenario

A business (Globex Ltd, reg `12345678`) starts onboarding. A KYB workflow
runs a **paid** bureau verification — Companies House + sanctions + UBO
screen — at $12 per check. Workflows get retried: a flaky run, a duplicate
trigger, an operator hitting submit twice. Each re-run bills the bureau
again and re-screens an entity whose KYB decision is already made.

**KIFF makes the check once-and-done** because the verification advances
the business `PENDING → VERIFIED`. `RUN_KYB_CHECK` is only allowed from
`PENDING`. Once verified, every re-run returns `state_not_allowed`. One
check, one fee, one decision.

This is the structured-pipeline point: the **state machine — not the
workflow runner — enforces once-and-done**. The workflow can be retried,
resumed, or triggered twice; KIFF still guarantees the irreversible,
billable step happens a single time.

## Guardrails PLUS KIFF (not instead of)

Two safety layers, stacked, not competing:

| Layer | Agno mechanism | Question it answers | Example |
|---|---|---|---|
| **Framework guardrails** | `pre_hooks=[PIIDetectionGuardrail()]` | Is the **input** safe to send to the model? | redact a director's personal data in the prompt |
| **KIFF** | `tool_hooks=[agno_hook(guard)]` | May this **action** run given the onboarding state? | block a second paid bureau check once VERIFIED |

The guardrail keeps the input clean; KIFF keeps the bureau call
once-and-done. The recipe attaches the PII guardrail when the installed
Agno build ships it, and degrades cleanly when it does not — KIFF never
depends on a framework guardrail being present.

## Architecture

1. **kiff-decide** (Go): the KIFF gate with a KYB domain
   (Business: `PENDING → VERIFIED`). `RUN_KYB_CHECK` allowed only from
   `PENDING`.
2. **app/server.py** (Python stdlib): the system of record. `/verify` is
   deliberately non-idempotent and **not free** — every call charges a
   $12 bureau fee.
3. **agent/kyb_workflow.py**: a real **Agno Workflow** (intake → verify →
   decision) whose `verify` step runs an agent (gpt-4o-mini) with a
   `run_kyb_check` tool guarded via `agno_hook(guard)`.
4. **driver/scenario.py**: proof script showing WITHOUT vs WITH KIFF.

> Note: if the installed Agno build does not expose `agno.workflow`, the
> recipe falls back to running the `verify` agent directly. The KIFF
> guarantee (one paid check, the rest blocked) is identical either way —
> the workflow is the orchestration shape, the gate is the guarantee.

## Run locally

```bash
# Terminal 1: build + start the gate
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide

# Terminal 2: start the KYB app
cd app && python3 server.py

# Terminal 3: install deps and run the proof
python3 -m venv .venv && source .venv/bin/activate
pip install agno openai
cd driver && python3 scenario.py
```

## Connect to KIFF Cloud

Set `KIFF_CLOUD_API_KEY` and the guard registers as a live runtime in your
dashboard under:
- project: `cookbook`
- environment: `aws`
- workflow: `kyb-verification`
- adapter: `agno`

## Expected output

```
==================================================================
  WITHOUT KIFF — ungoverned: the bureau check re-runs and re-bills
==================================================================
business biz-nokiff-...: Acme Ltd, reg=12345678
workflow re-runs the paid bureau check 5 times...
  check 1: #1 (bureau fee: $12.00)
  check 2: #2 (bureau fee: $12.00)
  check 3: #3 (bureau fee: $12.00)
  check 4: #4 (bureau fee: $12.00)
  check 5: #5 (bureau fee: $12.00)

  RESULT: 5 bureau checks, $60.00 in fees — WASTED SPEND + RE-SCREENING

==================================================================
  WITH KIFF — real Agno Workflow enforces once-and-done verification
==================================================================
business biz-kiff-... seeded: Globex Ltd, state=PENDING
  Connected to KIFF Cloud: runtime=grt_...
running KYB pipeline as Agno Workflow (real gpt-4o-mini)...
  workflow response: KYB decision recorded ...
  state: VERIFIED
  after workflow: 1 bureau check(s)
retry storm: 4 more runs of the verify step...
  re-run 2: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified...)
  re-run 3: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified...)
  re-run 4: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified...)
  re-run 5: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified...)

  RESULT: 1 bureau check(s), $12.00 in fees; 4 blocked by KIFF

==================================================================
  VERDICT
==================================================================
  WITHOUT KIFF : 5 checks, $60.00 in fees   FAIL — wasted bureau spend + re-screening
  WITH KIFF    : 1 check(s), $12.00 in fees, 4 blocked   PASS

  PROOF: the real workflow's verification ran exactly once. KIFF blocked
  every re-run once the business moved to VERIFIED — no double bureau fee,
  no re-screening a decided entity.
```

## What's being proven

1. **The gate + app loop works**: WITHOUT KIFF = 5 paid checks ($60); WITH
   KIFF = 1 check ($12), 4 blocked.
2. **The real workflow works**: a real gpt-4o-mini agent inside an Agno
   Workflow `verify` step called `run_kyb_check`; the `agno_hook`
   intercepted it and KIFF allowed it (state=PENDING).
3. **Once-and-done is enforced**: after the check, `KYB_VERIFIED` advances
   the business to VERIFIED, and KIFF's `state_not_allowed` blocks every
   subsequent run of the verify step — no matter how the workflow retries.
4. **Guardrails + KIFF stack**: Agno's `PIIDetectionGuardrail` (input
   safety) and KIFF (action authority) run as separate hooks without
   conflict.
5. **KIFF Cloud visibility**: the runtime is registered and shows live in
   the dashboard with heartbeat.
