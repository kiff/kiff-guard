# PROOF — instant-payout-enablement-guard

Real run on **AWS Bedrock (`amazon.nova-pro-v1:0`)**, gate on
`github.com/kiff/kiff` **v0.6.0**, Agno v2 (`agno 2.6.20`). The agent ships
the instant payout; once the escrow is `DISBURSED`, every repeat is a no-op.

## Output

```
==================================================================
  WITHOUT KIFF — ungoverned: payout fires on every retry
==================================================================
escrow escrow-nokiff-... created + cleared: $249.00 to seller-001
  payout 1: sent $249.00 (#1)
  payout 2: sent $249.00 (#2)
  payout 3: sent $249.00 (#3)
  payout 4: sent $249.00 (#4)
  payout 5: sent $249.00 (#5)
  RESULT: 5 disbursements, $1,245.00 paid out — DUPLICATE PAYOUTS

==================================================================
  WITH KIFF — real agent ships instant payout; the repeat is declined
==================================================================
escrow escrow-kiff-... created + cleared: $249.00, state=CLEARED
  model: AwsBedrock (MODEL_PROVIDER=bedrock)

agent (real model via Agno) disburses escrow instantly...
  agent response: <thinking> The escrow has cleared, so I need to disburse the payout...
  state after payout: DISBURSED

agent retries the payout 4 more times...
  attempt 2: BLOCKED by KIFF (escrow is "DISBURSED" — payout allowed only when CLEARED)
  attempt 3: BLOCKED by KIFF (escrow is "DISBURSED" — payout allowed only when CLEARED)
  attempt 4: BLOCKED by KIFF (escrow is "DISBURSED" — payout allowed only when CLEARED)
  attempt 5: BLOCKED by KIFF (escrow is "DISBURSED" — payout allowed only when CLEARED)

  RESULT: 1 payout, $249.00 disbursed; 4 repeats declined

==================================================================
  VERDICT
==================================================================
  WITHOUT KIFF : 5 payouts ($1,245)     FAIL — duplicate payouts
  WITH KIFF    : 1 payout ($249), 4 declined   PASS — instant payout shipped
```

## What it shows

You remove the manual review gate because the state machine holds the
invariant — each escrow pays out once, by construction. The agent ships
payouts instantly the moment `CLEARED`; the boundary makes it safe.
