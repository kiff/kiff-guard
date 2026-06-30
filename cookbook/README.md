# KIFF Cookbook

Real-world recipes proving KIFF stops risky agent actions before they execute.

Each recipe is a **complete, runnable proof**: real models, real agent frameworks,
real side effects, real KIFF runtime. Every recipe connects to KIFF Cloud so
decisions and receipts are visible in the dashboard.

## Start here: observe (no KIFF account)

New to KIFF? Begin with **[observe-quickstart](./observe-quickstart/)** — it
proves the observe-mode claim (audit trail + derived domain with **no KIFF
account, no gate, no API call**) and runs offline with zero keys. It's the
on-ramp before the enforce recipes below.

## Custom agent / non-SDK stack: govern over plain HTTP

No adapter, no SDK? **[custom-agent-http](./custom-agent-http/)** shows that
a proposal is one `POST /v1/proposals/decide` — runnable from shell or Go,
with the fail-safe rule (run only on `allowed`). The on-ramp for Ruby, Go,
shell, or any stack the Python/TS SDKs don't cover.

## Recipes

| # | Recipe | Scenario | Adapter | Proof |
|---|--------|----------|---------|-------|
| 1 | [duplicate-payment-guard](./duplicate-payment-guard/) | AP agent retries a $10K payment 10× → $100K risk | OpenClaw (TS) | $100K → $10K, 9 blocked |
| 2 | [refund-ceiling-guard](./refund-ceiling-guard/) | Support agent retries a $50 refund 5× on a $100 order → $250 refunded | LangGraph | $250 → $100, 3 blocked |
| 3 | [collections-promise-guard](./collections-promise-guard/) | Collections agent contacts a borrower after a promise to pay → FDCPA/CONC risk | Agno | 5 contacts → 1, 4 blocked |
| 4 | [chargeback-dispute-guard](./chargeback-dispute-guard/) | Disputes agent submits same chargeback 5× → $125 in scheme fees | Strands | $125 → $25, 4 blocked |
| 5 | [vulnerability-escalation-guard](./vulnerability-escalation-guard/) | A whole customer-ops **team** keeps acting after a vulnerability signal → FCA Consumer Duty failure | Agno **Teams** | 6 actions → 1, whole team halted by one event |
| 6 | [kyb-verification-guard](./kyb-verification-guard/) | A KYB **workflow** re-runs a paid bureau check 5× → $60 + re-screening | Agno **Workflows** | $60 → $12, 4 blocked (once-and-done) |

## Enablement recipes

A second family, same proof rig, opposite framing. Instead of leading with the
block, these lead with the agent *doing the work*: a real Agno agent performs
the legitimate revenue/ops action (KIFF allows it, state advances), then is
declined on every repeat once state moves on. The boundary is what makes putting
the agent on the task shippable in the first place.

E2–E5 are built on `kiff/kiff v0.6.0` with policy-owned roles (`AssignRole`) and
Agno v2; refund-enablement (E1) is the earlier proof on `kiffhq/kiff v0.2.0`.

| # | Recipe | Scenario | Adapter | Proof |
|---|--------|----------|---------|-------|
| E1 | [refund-enablement-guard](./refund-enablement-guard/) | Agent issues a refund on a `PAID` order (allowed); declined on every retry once `REFUNDED` | Agno | 1 refund, 4 repeats declined |
| E2 | [deal-close-enablement-guard](./deal-close-enablement-guard/) | Sales agent applies a closing discount on an `OPEN` deal; cannot stack a second once `DISCOUNTED` | Agno | 1 discount, 4 declined |
| E3 | [payment-recovery-enablement-guard](./payment-recovery-enablement-guard/) | Dunning agent retries a charge on a `PAST_DUE` invoice; declined once `RECOVERED` | Agno | 1 charge, 4 declined |
| E4 | [instant-payout-enablement-guard](./instant-payout-enablement-guard/) | Payout agent disburses the moment escrow `CLEARED`; declined once `DISBURSED` | Agno | 1 payout, 4 declined |
| E5 | [prompt-injection-refund-guard](./prompt-injection-refund-guard/) | **Adversarial**: a customer message social-engineers a support agent toward a second refund — or a fallback store credit — on an already-`REFUNDED` order | Agno | 0 extra payouts; 2/2 money paths declined |

E5 is the adversarial case: the agent has **two** money tools (refund and
credit), both gated, and the guarantee holds regardless of whether the model is
persuaded — the boundary lives outside the agent's reasoning.

## What each recipe proves

All recipes share the same architecture and proof pattern:

1. **WITHOUT KIFF** — the ungoverned baseline shows what happens when agents retry or over-act: money lost, fees incurred, regulations violated.
2. **WITH KIFF** — a real LLM (gpt-4o-mini) running in a real agent framework makes the first legitimate call. KIFF allows it, state advances. Every later action the state forbids is blocked.
3. **KIFF Cloud** — each recipe registers a live runtime in the dashboard. Receipts, decisions, and audit trail visible in real time, kept active by a heartbeat.

## Guardrails PLUS KIFF — different layers, they stack

KIFF is **not** a guardrails replacement. Framework guardrails answer *"is
the input safe?"* (PII, prompt injection, moderation, schema). KIFF answers
*"may this action run, given state + policy?"*. They sit at different points
and compose:

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[offer_product],
    pre_hooks=[PIIDetectionGuardrail()],   # framework guardrail: input safety
    tool_hooks=[agno_hook(guard)],         # KIFF: action authority
)
```

Recipes 5 and 6 demonstrate the two layers running side by side: Agno's
`PIIDetectionGuardrail` (a `pre_hook`) scrubs a leaked SSN from the input,
while KIFF (a `tool_hook`) blocks the action because the entity's state
forbids it. Use what the framework gives you, **plus** KIFF.

## Adapters covered

Each recipe uses a different Python (or TS) adapter from `packages/`:

| Adapter | Shape | Hook | Recipe(s) |
|---------|-------|------|-----------|
| OpenClaw (TS) | vote | `before_tool_call` | 1 |
| LangGraph | middleware | `guard.evaluate()` inside `@tool` | 2 |
| Agno | middleware | `tool_hooks=[agno_hook(guard)]` | 3, 5, 6, E1–E5 |
| Strands | vote | `BeforeToolCallEvent` via `kiff_hook_provider` | 4 |

Recipe 3 uses a single Agno agent; recipe 5 uses an Agno **Team**
(multi-agent, one shared guard); recipe 6 uses an Agno **Workflow**
(structured pipeline). Same adapter, three orchestration shapes — the guard
is identical in all three.

## KIFF Cloud runtimes (live proofs)

| Recipe | Runtime ID | Adapter | Workflow |
|--------|-----------|---------|----------|
| refund-ceiling-guard | grt_7617bfedced8a04a | langgraph | refund-ceiling |
| collections-promise-guard | grt_abf614d6f4bfba9c | agno | collections-promise |
| chargeback-dispute-guard | grt_50a5e51abb54d5cb | strands | chargeback-dispute |
| vulnerability-escalation-guard | grt_e21d38003d63d61e | agno | vulnerability-escalation |
| kyb-verification-guard | grt_d66e423509953c46 | agno | kyb-verification |

## Common structure

Every recipe follows the same layout:

```
<recipe-name>/
├── README.md       scenario, architecture, expected output
├── PROOF.md        live proof record with actual terminal output
├── MANIFEST.md     complete file inventory + reproducibility checklist
├── .env.example    secrets template
├── requirements.txt
├── kiff-decide/    the KIFF gate (Go, wraps github.com/kiffhq/kiff v0.2.0)
├── app/            system of record (deliberately non-idempotent)
├── agent/          the real agent using the adapter
└── driver/         proof script (WITHOUT vs WITH KIFF)
```

Every recipe carries its own `README.md` and `PROOF.md`. The enforce recipes
(1–6) also include `MANIFEST.md`; the enablement recipes (E1–E5) keep the same
`README.md` + `PROOF.md` convention and, for E2–E5, build on the migrated
`github.com/kiff/kiff v0.6.0` gate (policy-owned roles via `AssignRole`).

## How to run any recipe

```bash
cd cookbook/<recipe-name>
cp .env.example .env && $EDITOR .env  # set OPENAI_API_KEY, KIFF_CLOUD_API_KEY

# build the gate
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide &

# start the system of record
python3 app/server.py &

# install Python deps and run the proof
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd driver && python3 scenario.py
```

## License

MIT (framework + guard SDK). Recipes are reference implementations.
