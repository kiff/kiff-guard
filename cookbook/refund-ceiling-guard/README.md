# refund-ceiling-guard

A cookbook recipe proving KIFF stops an over-refund attack where an AI
support agent is tricked (or retries) into issuing the same refund
multiple times, exceeding the order total.

**Adapter**: LangGraph (`wrap_tool_call` middleware shape)

## The scenario

A customer orders $100 of goods. The support agent issues a $50 partial
refund. A retry loop (flaky connection, prompt injection, model drift)
makes the same $50 refund call 5 times → $250 refunded on a $100 order.

**KIFF blocks the over-refund** because the order state advances:
PAID → PARTIALLY_REFUNDED → FULLY_REFUNDED. Once fully refunded, the
gate returns `state_not_allowed` for any further ISSUE_REFUND action.

## Architecture

1. **kiff-decide** (Go): the KIFF gate with an order-refunds domain
   (Order: PAID → PARTIALLY_REFUNDED → FULLY_REFUNDED)
2. **app/server.py** (Python stdlib): the system of record. `/refund` is
   deliberately non-idempotent — every call credits money.
3. **driver/scenario.py**: proof script showing WITHOUT vs WITH KIFF

## Run locally

```bash
# Terminal 1: build + start the gate
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide

# Terminal 2: start the refund app
cd app && python3 server.py

# Terminal 3: run the proof
cd driver && python3 scenario.py
```

## Connect to KIFF Cloud

Set `KIFF_CLOUD_API_KEY` and the guard will register as a runtime in
your dashboard under project=cookbook, environment=aws, workflow=refund-ceiling.

## Expected output

```
==================================================================
  WITHOUT KIFF — ungoverned: every retry refunds
==================================================================
order ord-nokiff-... created: $100.00
retrying $50 refund 5 times...
  attempt 1: refunded $50.00 (#1)
  attempt 2: refunded $50.00 (#2)
  attempt 3: refunded $50.00 (#3)
  attempt 4: refunded $50.00 (#4)
  attempt 5: refunded $50.00 (#5)

  RESULT: $250.00 refunded across 5 refunds (order was $100.00)

==================================================================
  WITH KIFF — the gate enforces the refund ceiling
==================================================================
order ord-kiff-... created + seeded: $100.00, state=PAID
retrying $50 refund 5 times through the guard...
  attempt 1: ALLOWED (refund #1)
  attempt 2: ALLOWED (refund #2)
  attempt 3: BLOCKED by KIFF (order is in state "FULLY_REFUNDED"...)
  attempt 4: BLOCKED by KIFF (order is in state "FULLY_REFUNDED"...)
  attempt 5: BLOCKED by KIFF (order is in state "FULLY_REFUNDED"...)

  RESULT: $100.00 refunded across 2 refund(s); 3 blocked by KIFF.

==================================================================
  VERDICT
==================================================================
  WITHOUT KIFF : $250.00 refunded (5 refunds)   FAIL — exceeds order total
  WITH KIFF    : $100.00 refunded (2 refund(s))    PASS — capped at order total

  PROOF: each $50 refund call was legitimate. Only a state-aware gate
  stopped the over-refund once the order reached its ceiling.
```
