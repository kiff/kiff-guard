# payment-recovery-enablement-guard

**Let an agent work past-due invoices. It charges once to recover; the repeat is declined.**

An enablement recipe: it leads with the agent *doing the revenue-recovery work*.
A real Agno (v2) agent retries the charge on a `PAST_DUE` invoice and it goes
through, then the same agent is declined when it retries again, because the
invoice is no longer `PAST_DUE`. The boundary is what lets you put the agent on
dunning at all — it charges the card once to recover, it does not hammer it.

## Domain

`Invoice` moves `CREATED → PAST_DUE → RECOVERED`. `RETRY_PAYMENT` is allowed
only from `PAST_DUE`. Once the charge recovers the payment, the invoice advances
to `RECOVERED` and further retries are refused with `state_not_allowed`.

## Model picker

- `MODEL_PROVIDER=openai` (default) — `OpenAIChat`, no AWS needed.
- `MODEL_PROVIDER=bedrock` — `agno.models.aws.AwsBedrock` (e.g. `amazon.nova-pro-v1:0`,
  or a `us.anthropic.claude-*` id for Bedrock-hosted Claude).

Set `MODEL_ID` to override. Built on Agno v2 (`agno>=2.6,<3`) and
`github.com/kiff/kiff` v0.6.0.

## Architecture

```
payment-recovery-enablement-guard/
├── kiff-decide/   the KIFF gate (Go, wraps github.com/kiff/kiff v0.6.0)
├── app/           payment-app: system of record (non-idempotent /charge)
├── agent/         the Agno agent (retry_payment tool, guarded by agno_hook)
└── driver/        proof script (WITHOUT vs WITH KIFF)
```

## Run it

```bash
cd cookbook/payment-recovery-enablement-guard
cp .env.example .env && $EDITOR .env   # set OPENAI_API_KEY (or AWS creds)

cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide &
cd ..
python3 app/server.py &
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 driver/scenario.py
```

## Expected loop

```
WITHOUT KIFF : 5 charges hit            FAIL — card hammered
WITH KIFF    : 1 charge, 4 declined     PASS — agent recovered the payment; repeats declined
```

The real agent recovers the payment on its own (allowed); KIFF declines every
repeat once the invoice is no longer `PAST_DUE`. You ship the agent on recovery.
