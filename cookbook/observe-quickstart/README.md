# observe-quickstart

**See what your agent actually does — with no KIFF account, in under a minute.**

Every other recipe in this cookbook runs KIFF in **enforce** mode: a real
kiff-decide gate decides each action before it runs. This recipe is the
on-ramp *before* that — it proves the **observe** half of the SDK's
headline claim:

> observe — runs every tool, records an audit trail, and learns the action
> catalog. **No KIFF account, no domain, no API call required.**

## What it proves

With one line — `Guard(mode="observe")` — and nothing else (no client, no
tenant, no kiff-decide gate, no cloud, no API call to KIFF), the guard:

1. **records a real audit trail** — one `observed` receipt per tool call,
2. **learns the action catalog** — tool names + parameter shapes from real
   traffic, and
3. **derives a starter domain** — a schema-valid `kiff.yaml` draft you can
   refine and activate when you're ready to enforce.

Observe never calls KIFF and never blocks a tool. It is decide-independent
by construction.

## Run it

```bash
cd cookbook/observe-quickstart
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Default: offline, zero keys — replays a scripted agent transcript
# through the real agno adapter.
python3 driver/scenario.py

# Optional: run a real Agno agent (gpt-4o-mini) instead.
OPENAI_API_KEY=sk-... python3 driver/scenario.py --live
```

The offline path needs **no API keys and no network** — it replays a
scripted transcript of tool calls through the same `agno_hook(guard)` a
live agent would use, so the observe path is exercised for real. The
`--live` path runs an actual Agno agent if you set `OPENAI_API_KEY`.

> Note: the only KIFF-unrelated requirement is the agent framework itself
> (`agno`) and, for `--live`, an OpenAI key. KIFF needs nothing.

## Expected output

```
AUDIT TRAIL — 5 observed receipt(s)
  [observed] refund_order  (observed)
  [observed] send_email  (observed)
  [observed] refund_order  (observed)
  [observed] escalate_ticket  (observed)
  [observed] send_email  (observed)

DERIVED DOMAIN DRAFT (from observed traffic)
domain: support-ops
entity: Entity   # TODO(human): ...
...
actions:
  - name: refund_order
    required_parameters: [amount_cents, order_id, reason]
    risk: low
    approval: never
    ...

PROOF: every tool ran and was audited with no KIFF account, no tenant,
no gate, no API call. Exit 0.
```

## The next step (enforce)

When you're ready to govern rather than just observe:

1. Refine the derived draft (fill in the `TODO(human)` states, risk, and
   approval), or push it straight to the authoring UI with a credential:
   `guard.save_draft("support-ops")`.
2. Switch to `Guard(client=HTTPClient(...), tenant=..., mode="enforce")`.
3. The same `agno_hook(guard)` now asks KIFF to clear each action before it
   runs — see the other cookbook recipes for the enforce-mode proofs.

## Files

```
observe-quickstart/
├── README.md
├── requirements.txt
├── agent/
│   └── support_agent.py   # Agno agent + observe-mode guard; scripted transcript
└── driver/
    └── scenario.py        # runs offline (default) or --live; prints trail + draft
```
