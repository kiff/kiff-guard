# chargeback-dispute-guard

A cookbook recipe proving KIFF stops a disputes agent from submitting the
same chargeback twice — preventing duplicate submissions to Visa/Mastercard
that carry penalty fees and can get the issuer flagged.

**Adapter**: Strands (`BeforeToolCallEvent` vote shape)

## The scenario

A customer disputes a $150 fraudulent charge (reason code 10.4). The
disputes agent investigates, classifies it, and submits the chargeback.
A retry loop then tries to submit the same chargeback 4 more times —
each duplicate submission incurs a $25 scheme fee and risks scheme
penalties for excessive chargebacks.

**KIFF blocks the duplicate submissions** because after the first
SUBMIT_CHARGEBACK is allowed (state=INVESTIGATED), the state advances to
SUBMITTED. Every subsequent attempt returns `state_not_allowed`.

## Architecture

1. **kiff-decide** (Go): the KIFF gate — Dispute: FILED → INVESTIGATED → SUBMITTED → RESOLVED
2. **app/server.py** (Python stdlib): system of record. `/submit` is
   non-idempotent — every call charges a $25 scheme fee.
3. **agent/disputes_agent.py**: real Strands agent (gpt-4o-mini) with
   `submit_chargeback` tool guarded via `kiff_hook_provider(guard)`.
4. **driver/scenario.py**: proof showing WITHOUT vs WITH KIFF.

## Run locally

```bash
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide &
python3 app/server.py &
python3 -m venv .venv && source .venv/bin/activate
pip install strands-agents strands-agents-tools openai
cd driver && python3 scenario.py
```

## Connect to KIFF Cloud

Set `KIFF_CLOUD_API_KEY` — the guard registers as:
- project: `cookbook`, environment: `aws`
- workflow: `chargeback-dispute`, adapter: `strands`
