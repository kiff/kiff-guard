# PROOF — payment-recovery-enablement-guard

Real run, captured locally. A real Agno (v2) agent on **AWS Bedrock
(`amazon.nova-pro-v1:0`)** retries a charge through the KIFF gate
(`github.com/kiff/kiff` **v0.6.0**). The legitimate recovery charge executes;
once the invoice leaves `PAST_DUE`, every repeat is declined. Not scripted —
the agent picks the tool call; KIFF decides.

## Setup

- Gate: `kiff-decide` (Go, `kiff/kiff v0.6.0`) on `:8081`, domain `payment-recovery-enablement`.
- System of record: `payment-app` on `:8082` (non-idempotent `/charge`).
- Agent: Agno v2 (`agno 2.6.20`), `MODEL_PROVIDER=bedrock MODEL_ID=amazon.nova-pro-v1:0`.

## Output

```
==================================================================
  WITHOUT KIFF — ungoverned: agent hits the card on every retry
==================================================================
invoice inv-nokiff-... created + past due: $49.00
agent retries the charge, then retries 4 more times...
  charge 1: hit the card $49.00 (#1)
  charge 2: hit the card $49.00 (#2)
  charge 3: hit the card $49.00 (#3)
  charge 4: hit the card $49.00 (#4)
  charge 5: hit the card $49.00 (#5)

  RESULT: 5 charges, $245.00 hit on a $49.00 invoice — CARD HAMMERED

==================================================================
  WITH KIFF — real agent recovers the payment; the repeat is declined
==================================================================
invoice inv-kiff-... created + past due: $49.00, state=PAST_DUE
  model: AwsBedrock (MODEL_PROVIDER=bedrock)

agent (real model via Agno) recovers invoice inv-kiff-...
  agent response: <thinking> I need to recover the past-due invoice ...
  state after recovery: RECOVERED

agent retries the charge 4 more times...
  attempt 2: BLOCKED by KIFF (invoice is "RECOVERED" — retry allowed only while PAST_DUE)
  attempt 3: BLOCKED by KIFF (invoice is "RECOVERED" — retry allowed only while PAST_DUE)
  attempt 4: BLOCKED by KIFF (invoice is "RECOVERED" — retry allowed only while PAST_DUE)
  attempt 5: BLOCKED by KIFF (invoice is "RECOVERED" — retry allowed only while PAST_DUE)

  RESULT: 1 charge(s), $49.00 recovered; 4 repeat(s) declined

==================================================================
  VERDICT
==================================================================
  WITHOUT KIFF : 5 charges hit       FAIL — card hammered
  WITH KIFF    : 1 charge(s), 4 declined   PASS — agent recovered the payment; repeats declined

  PROOF: the real agent recovered the payment on its own (allowed), and KIFF
  declined every repeat once the invoice was no longer PAST_DUE. You ship the agent.
```

## What it shows

Enablement framing: you *put the agent on payment recovery* — it does the
revenue-recovery work autonomously — and the boundary makes it shippable. Once
the invoice leaves `PAST_DUE`, KIFF turns every further charge into a no-op
(`state_not_allowed`), so the agent recovers the payment without hammering the
customer's card. The action is the recovery work; the boundary is what lets you
hand it to the agent.
