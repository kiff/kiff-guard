# Proof Record: kyb-verification-guard

**Date**: 2026-06-04
**Instance**: EC2 t3.large, us-east-1d (i-008692d750b341a67, 13.221.5.207)
**Framework**: github.com/kiffhq/kiff v0.2.0 (public, MIT)
**Guard SDK**: kiff-guard Python v0.1.0 (MIT)
**Agent framework**: Agno 2.6.11 — **Workflows** (agno_hook middleware shape)
**Model**: OpenAI gpt-4o-mini
**KIFF Cloud runtime**: grt_d66e423509953c46

## What was proven

A complete end-to-end integration of KIFF making a paid KYB verification
run **exactly once** inside a structured Agno Workflow:

- A **real OpenAI model** (gpt-4o-mini)
- A **real Agno Workflow** (intake -> verify -> decision pipeline)
- A **real KIFF runtime** (public framework v0.2.0)
- A **real Python guard SDK** (kiff-guard with the agno adapter)
- A **real system of record** (kyb-app, deliberately non-idempotent, $12/check)
- **Agno guardrails stacked with KIFF** (PIIDetectionGuardrail pre_hook +
  agno_hook tool_hook)
- **KIFF Cloud connected** (runtime visible in dashboard, heartbeat running)

## The scenario

A business (Globex Ltd, reg 12345678) starts onboarding in state PENDING.
A KYB workflow runs a paid bureau verification (Companies House + sanctions
+ UBO screen) at $12 per check. Workflows get retried — flaky runs,
duplicate triggers, operator re-submits — and each re-run re-bills the
bureau and re-screens an already-decided entity. The verification must run
once and only once.

## Results (verified live on EC2, 2026-06-04)

### WITHOUT KIFF (ungoverned baseline)
```
business biz-nokiff-ad3205: Acme Ltd, reg=12345678
workflow re-runs the paid bureau check 5 times...
  check 1: #1 (bureau fee: $12.00)
  check 2: #2 (bureau fee: $12.00)
  check 3: #3 (bureau fee: $12.00)
  check 4: #4 (bureau fee: $12.00)
  check 5: #5 (bureau fee: $12.00)

RESULT: 5 bureau checks, $60.00 in fees — WASTED SPEND + RE-SCREENING
```

### WITH KIFF (state-aware gate, real Agno Workflow)
```
business biz-kiff-ad3205 seeded: Globex Ltd, state=PENDING
  Connected to KIFF Cloud: runtime=grt_d66e423509953c46
running KYB pipeline as Agno Workflow (real gpt-4o-mini)...
  workflow response: KYB decision recorded. Prior step: Onboard business biz-kiff-ad3205.
                     Run the KYB check with registration_number=12345678...
  state: VERIFIED
  after workflow: 1 bureau check(s)
retry storm: 4 more runs of the verify step...
  re-run 2: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified, re-check blocked)
  re-run 3: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified, re-check blocked)
  re-run 4: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified, re-check blocked)
  re-run 5: BLOCKED by KIFF (business is "VERIFIED" — KYB already verified, re-check blocked)

RESULT: 1 bureau check(s), $12.00 in fees; 4 blocked by KIFF
```

### Verdict
```
WITHOUT KIFF : 5 checks, $60.00 in fees   FAIL — wasted bureau spend + re-screening
WITH KIFF    : 1 check(s), $12.00 in fees, 4 blocked   PASS

PROOF: the real workflow's verification ran exactly once. KIFF blocked
every re-run once the business moved to VERIFIED — no double bureau fee,
no re-screening a decided entity.
```

Exit code: 0 (proof passed)

## What the proof shows

1. **The gate works**: kiff-decide evaluates RUN_KYB_CHECK against the
   Business state machine — allowed from PENDING, blocked
   (state_not_allowed) once VERIFIED.

2. **The Agno Workflow integration works**: the recipe ran as a real Agno
   Workflow (intake -> verify -> decision), confirmed by the pipeline
   response ("KYB decision recorded. Prior step: ..."). The verify step's
   agent (gpt-4o-mini) called `run_kyb_check`; the `agno_hook(guard)`
   intercepted it and KIFF allowed it (state=PENDING).

3. **Once-and-done is enforced**: the cleared check ingested KYB_VERIFIED,
   advancing the business to VERIFIED. Every subsequent run of the verify
   step returned state_not_allowed — one paid check, the other four
   blocked, regardless of how the workflow retried.

4. **Guardrails PLUS KIFF stack**: Agno's PIIDetectionGuardrail (pre_hook,
   input safety) and KIFF (tool_hook, action authority) attach to the
   verify agent together without conflict. The guardrail keeps the input
   clean; KIFF keeps the bureau call once-and-done.

5. **KIFF Cloud visibility**: the runtime registered via `connect_guard()`
   (grt_d66e423509953c46) and a heartbeat keeps it active.

## Note on the Workflow dependency

`agno.workflow` imports `fastapi` transitively. With fastapi installed the
recipe runs the real Workflow pipeline; without it, the recipe degrades to
running the verify agent directly (the KIFF guarantee — one paid check, the
rest blocked — is identical either way). `fastapi` is pinned in
`requirements.txt` so the Workflow path is the default.

## Teardown checklist

- [x] Proof passed (exit 0)
- [x] KIFF Cloud runtime active (grt_d66e423509953c46)
- [x] README + MANIFEST + PROOF written
- [x] All source files in repo
- [ ] EC2 instance terminates via 2h TTL (shutdown -h +120 at launch)
- [ ] Security group + key pair cleaned up post-shutdown
- [ ] OpenAI key to be rotated (in transcript)
