# Proof Record: refund-ceiling-guard

**Date**: 2026-06-03
**Instance**: EC2 t3.medium, us-east-1 (i-05f3a2119d41d1260, 18.208.246.19)
**Framework**: github.com/kiffhq/kiff v0.2.0 (public, MIT)
**Guard SDK**: kiff-guard Python v0.1.0 (MIT)
**Agent framework**: LangGraph (evaluate middleware shape)
**Model**: OpenAI gpt-4o-mini
**KIFF Cloud runtime**: grt_7617bfedced8a04a

## What was proven

A complete end-to-end integration of KIFF blocking an over-refund where an
AI support agent is triggered (or retried) into issuing the same $50 refund
multiple times on a $100 order:

- A **real OpenAI model** (gpt-4o-mini)
- A **real agent framework** (LangGraph ReAct agent)
- A **real KIFF runtime** (public framework v0.2.0)
- A **real Python guard SDK** (kiff-guard with guard.evaluate())
- A **real system of record** (refund-app, deliberately non-idempotent)
- **KIFF Cloud connected** (runtime visible in dashboard)

## Results (verified live on EC2, 2026-06-03)

### WITHOUT KIFF (ungoverned baseline)
```
order ord-nokiff-... created: $100.00
retrying $50 refund 5 times...
  attempt 1: refunded $50.00 (#1)
  attempt 2: refunded $50.00 (#2)
  attempt 3: refunded $50.00 (#3)
  attempt 4: refunded $50.00 (#4)
  attempt 5: refunded $50.00 (#5)

RESULT: $250.00 refunded across 5 refunds (order was $100.00)
```

### WITH KIFF (state-aware gate, real LangGraph agent)
```
order ord-kiff-... created + seeded: $100.00, state=PAID
  Connected to KIFF Cloud: runtime=grt_7617bfedced8a04a
agent (real gpt-4o-mini) asked to refund $50.00...
  agent response: The refund of 5000 cents for order ord-kiff-... has been
                  successfully processed. The tota...
  after agent: 1 refund(s), $50.00 refunded
retry storm: 4 more attempts through the guard...
  attempt 2: ALLOWED (refund #2)
  attempt 3: BLOCKED by KIFF (order is in state "FULLY_REFUNDED"...)
  attempt 4: BLOCKED by KIFF (order is in state "FULLY_REFUNDED"...)
  attempt 5: BLOCKED by KIFF (order is in state "FULLY_REFUNDED"...)

RESULT: $100.00 refunded across 2 refund(s); 3 blocked by KIFF.
```

### Verdict
```
WITHOUT KIFF : $250.00 refunded (5 refunds)   FAIL — exceeds order total
WITH KIFF    : $100.00 refunded (2 refund(s))  PASS — capped at order total

PROOF: the real agent's $50 refund was legitimate. Only a state-aware
gate stopped the retry storm from over-refunding past the order ceiling.
```

Exit code: 0 (proof passed)

## Architecture verified

```
┌─────────────────────────────────────────────────────────────┐
│  LangGraph ReAct Agent (Python, gpt-4o-mini)                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  @tool issue_refund wraps guard.evaluate()           │   │
│  │  ↓                                                   │   │
│  │  HTTPClient → POST /v1/proposals/decide             │   │
│  │              → kiff-decide:8081                      │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  issue_refund tool body (if KIFF allows)            │   │
│  │  ↓                                                   │   │
│  │  POST /refund → refund-app:8082                     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         ↓ (after real refund)
┌────────────────────────┐    ┌──────────────────────────────┐
│  refund-app :8082      │    │  kiff-decide (Go :8081)      │
│  /refund (non-idempot) │    │  Domain: Order               │
│  /order, /ledger       │───▶│  PAID → PARTIALLY_REFUNDED   │
└────────────────────────┘    │       → FULLY_REFUNDED       │
                              └──────────────────────────────┘
                                        ↕
                              ┌──────────────────────────────┐
                              │  KIFF Cloud (api.kiff.dev)   │
                              │  runtime: grt_7617bfedced8a04a│
                              └──────────────────────────────┘
```

## Teardown checklist

- [x] Proof passed (exit 0)
- [x] KIFF Cloud runtime active (grt_7617bfedced8a04a)
- [x] README + MANIFEST + PROOF written
- [x] All source files in repo
- [x] EC2 instance terminated via 2h TTL
