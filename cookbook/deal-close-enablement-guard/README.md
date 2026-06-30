# deal-close-enablement-guard

**Let an agent close deals with a discount. It applies the real one; the repeat is declined.**

An enablement recipe: instead of leading with the block, it leads with the
agent *doing revenue work*. A real Agno (v2) agent applies a closing discount
on an `OPEN` deal and it goes through, then the same agent is declined when it
tries to stack a second discount, because the deal is no longer `OPEN`. The
boundary is what lets you put the agent on closing at all — it grants the
discount, it does not give margin away twice.

## Domain

`Deal` moves `CREATED → OPEN → DISCOUNTED`. `APPLY_DISCOUNT` is allowed only
from `OPEN`. Once a discount is applied, the deal advances to `DISCOUNTED` and
further discounts are refused with `state_not_allowed`.

## Model picker

The agent's model is selectable, so the same recipe runs on different providers
with no other change (the KIFF tool hook is model-agnostic):

- `MODEL_PROVIDER=openai` (default) — `OpenAIChat`, no AWS needed.
- `MODEL_PROVIDER=bedrock` — `agno.models.aws.AwsBedrock` (e.g. `amazon.nova-pro-v1:0`,
  or a `us.anthropic.claude-*` id for Bedrock-hosted Claude).

Set `MODEL_ID` to override the default id for the chosen provider. Built on
Agno v2 (`agno>=2.6,<3`, the kiff-guard `agno` extra).

## Architecture

```
deal-close-enablement-guard/
├── kiff-decide/   the KIFF gate (Go, wraps github.com/kiffhq/kiff v0.2.0)
├── app/           deal-app: system of record (non-idempotent /discount)
├── agent/         the Agno agent (apply_discount tool, guarded by agno_hook)
└── driver/        proof script (WITHOUT vs WITH KIFF)
```

## Run it

```bash
cd cookbook/deal-close-enablement-guard
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

## Expected loop

```
WITHOUT KIFF : 5 discounts stacked            FAIL — margin giveaway
WITH KIFF    : 1 discount, 4 declined         PASS — agent closed the deal; repeats declined
```

The real agent applies the closing discount on its own (allowed); KIFF declines
every repeat once the deal is no longer `OPEN`. You ship the agent on closing.
