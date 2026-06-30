# instant-payout-enablement-guard

**Let an agent disburse seller payouts instantly. The moment escrow clears, the money ships — once.**

An enablement recipe: it leads with the agent doing the work you kept behind a
manual review gate. A real Agno (v2) agent disburses to the seller the moment
escrow transitions to `CLEARED` — no human in the loop, no batch window. Once
the payout ships the escrow advances to `DISBURSED`, and KIFF declines any
further disbursement. The boundary is what makes instant payouts safe to ship:
you don't need the review gate to prevent double-payment, because the state
machine holds that invariant for you.

## Domain

`Escrow` moves `CREATED → CLEARED → DISBURSED`. `DISBURSE_PAYOUT` is allowed
only from `CLEARED`. Once the payout ships, the escrow is `DISBURSED` and
further disbursements are refused with `state_not_allowed`.

## Model picker

- `MODEL_PROVIDER=openai` (default) — `OpenAIChat`, no AWS needed.
- `MODEL_PROVIDER=bedrock` — `agno.models.aws.AwsBedrock` (e.g. `amazon.nova-pro-v1:0`).

Built on Agno v2 (`agno>=2.6,<3`) and `github.com/kiff/kiff` v0.6.0.

## Architecture

```
instant-payout-enablement-guard/
├── kiff-decide/   the KIFF gate (Go, wraps github.com/kiff/kiff v0.6.0)
├── app/           payout-app: system of record (non-idempotent /disburse)
├── agent/         the Agno agent (disburse_payout tool, guarded by agno_hook)
└── driver/        proof script (WITHOUT vs WITH KIFF)
```

## Run it

```bash
cd cookbook/instant-payout-enablement-guard
cp .env.example .env && $EDITOR .env

cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide &
cd ..
python3 app/server.py &
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 driver/scenario.py
```

## Expected loop

```
WITHOUT KIFF : 5 payouts sent ($249 on a $249 escrow)   FAIL — duplicate payouts
WITH KIFF    : 1 payout, 4 declined                      PASS — instant payout shipped; repeats declined
```
