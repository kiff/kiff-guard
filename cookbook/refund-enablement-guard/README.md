# refund-enablement-guard

**Let an agent issue refunds. It ships the legitimate one; the repeat is declined.**

The enablement counterpart to the other cookbook recipes. Instead of leading
with the block, this leads with the agent *doing the work*: a real Agno agent
issues a refund on a `PAID` order and it goes through, then the same agent is
declined when it retries, because the order is no longer `PAID`. The boundary is
what lets you hand the agent the refund route at all.

## Domain

`Order` moves `CREATED → PAID → REFUNDED`. `ISSUE_REFUND` is allowed only from
`PAID`. Once a refund issues, the order advances to `REFUNDED` and further
refunds are refused with `state_not_allowed`.

## Model picker

The agent's model is selectable, so the same recipe runs on different providers
with no other change (the KIFF tool hook is model-agnostic):

- `MODEL_PROVIDER=openai` (default) — `OpenAIChat`, no AWS needed.
- `MODEL_PROVIDER=bedrock` — `agno.models.aws.AwsBedrock` (e.g. `amazon.nova-pro-v1:0`).
- `MODEL_PROVIDER=claude` — `agno.models.aws.Claude` (Bedrock-hosted Claude).

Set `MODEL_ID` to override the default id for the chosen provider.

## Architecture

```
refund-enablement-guard/
├── kiff-decide/   the KIFF gate (Go, wraps github.com/kiffhq/kiff v0.2.0)
├── app/           refund-app: system of record (non-idempotent /refund)
├── agent/         the Agno agent (issue_refund tool, guarded by agno_hook)
└── driver/        proof script (WITHOUT vs WITH KIFF)
```

## Run it

```bash
cd cookbook/refund-enablement-guard
cp .env.example .env && $EDITOR .env   # set OPENAI_API_KEY (or AWS creds)

# build + start the gate
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide &
cd ..

# start the system of record
python3 app/server.py &

# install deps and run the proof
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 driver/scenario.py
```

## Expected loop (proven gate-only, no LLM)

```
seed                       → CREATED
PAYMENT_CAPTURED           → PAID
decide ISSUE_REFUND        → allowed   ("refund cleared; order can be refunded")
REFUND_ISSUED              → REFUNDED
decide ISSUE_REFUND again  → blocked   (state_not_allowed)
```

With the driver, the WITHOUT-KIFF baseline pays out on every retry (over-refund),
and the WITH-KIFF run shows the agent issuing the legitimate refund (allowed)
then KIFF declining each repeat.

> KIFF decides; your code executes. The refund payout here is a mock side effect
> in `app/`; KIFF never moves money. Connect `KIFF_CLOUD_API_KEY` to see the
> decisions and signed receipts in the dashboard.
