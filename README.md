# kiff-guard

**Drop-in KIFF clearance for any agent's tool calls.** One guard, two modes:

- **observe** — runs every tool, records an audit trail, and learns the
  action catalog. No KIFF account, no domain, no API call required. The
  fastest way to see what your agents actually do.
- **enforce** — asks KIFF to decide *before* each tool runs: `allowed`
  proceeds, anything else (`approval_required` / `blocked` / `invalid` /
  any future outcome) withholds. Fail-safe by construction.

The same one-line integration that governs your agent at runtime also
**derives a starter KIFF domain** from real traffic — so you never start
from a blank policy file.

> Part of [KIFF](https://kiff.dev) — the open-source operational foundation
> for agentic systems. Build the domain once, then connect any agent.
> This repo is the **client SDK + framework adapters**, MIT-licensed and
> community-maintainable. The framework lives at
> [`kiff/kiff`](https://github.com/kiff/kiff); the hosted runtime is
> KIFF Cloud.

## Repository layout

```
packages/
  python/kiff-guard/   # the Python SDK (shipped): core + 10 adapters
  js/                  # the TypeScript SDK (shipped): core + OpenClaw adapter
```

The guard is a **framework-agnostic core** plus **thin adapters**, one
per agent framework, each translating that framework's pre-tool-execution
seam into a single call to the core. The guard logic lives once; an
adapter adds no governance logic of its own.

> **Custom or no framework?** You don't need an adapter. The core (`Guard`
> + `HTTPClient`) governs any tool call directly over plain HTTP — the
> adapters are just convenience glue. See the "Custom agent? No adapter
> required" quickstart in
> [`packages/python`](./packages/python/kiff-guard/README.md#custom-agent-no-adapter-required)
> or [`packages/js`](./packages/js/README.md#custom-agent-no-adapter-required),
> and the raw-HTTP recipe in
> [`cookbook/custom-agent-http`](./cookbook/custom-agent-http/) for stacks
> the SDKs don't cover (Ruby, Go, shell).

## Python SDK

See [`packages/python/kiff-guard/README.md`](./packages/python/kiff-guard/README.md)
for install, quickstart, and per-framework usage.

```bash
pip install kiff-guard            # core, zero deps
pip install "kiff-guard[agno]"    # + a framework adapter's deps
```

```python
from kiff_guard import Guard
from kiff_guard.adapters.agno import agno_hook

guard = Guard(mode="observe")     # zero-config audit; no KIFF account
agent = Agent(model=..., tools=[...], tool_hooks=[agno_hook(guard)])
```

## Adapters

| Framework | Lang | Shape | Status |
|---|---|---|---|
| Agno | py | middleware (`tool_hooks`) | shipped |
| LangGraph / LangChain | py | middleware (`wrap_tool_call`) | shipped |
| Hermes (Nous) | py | vote (`pre_tool_call` plugin hook) | shipped |
| OpenAI Agents SDK | py | vote (tool input guardrail) | shipped |
| Google ADK | py | vote (`before_tool_callback`) | shipped |
| Pydantic AI | py | vote (`before_tool_execute` hook) | shipped |
| Strands Agents | py | vote (`BeforeToolCallEvent`) | shipped |
| Haystack Agents | py | vote (`ConfirmationStrategy`) | shipped |
| Microsoft Agent Framework | py | middleware (`FunctionMiddleware`, async) | shipped |
| OpenClaw | **ts** | vote (`before_tool_call`) | shipped (`@kiff/kiff-guard/adapters/openclaw`; seam + contract verified) |
| LlamaIndex | py | middleware (`GuardedAgentWorkflow` subclass, async) | shipped |

Two integration shapes: **middleware** (the guard runs the tool via a
handler continuation) and **vote / inverted-control** (the framework runs
the tool; the hook only votes allow/block). Each adapter documents its
verified pre-tool-execution seam and block contract in its module docstring.

## Contributing an adapter

Every adapter must pass the **conformance suite**
(`kiff_guard.conformance`) — a contract that pins the invariants all
adapters share (observe is decide-independent and one-receipt; enforce is
one-receipt; unknown outcomes fail safe; the trust boundary holds). Add a
small `drive` shim in `tests/test_conformance.py` and pass it; that's the
bar, not a line-by-line audit.

**Support tiers:** a small set of adapters are maintained tier-1; the rest
are community/best-effort. Each adapter pins the framework version range
it's tested against, and CI runs against each framework's latest so
breakage shows as a red badge, not a silent rot.

## TypeScript SDK

See [`packages/js/README.md`](./packages/js/README.md) for install,
quickstart, and usage.

```bash
npm install @kiff/kiff-guard
```

```typescript
import { Guard } from "@kiff/kiff-guard";
import { registerKiffGuard } from "@kiff/kiff-guard/adapters/openclaw";

const guard = new Guard({ mode: "observe" });  // zero-config audit
// register on OpenClaw plugin api (see package README for full example)
```

The TypeScript SDK is a faithful port of the Python SDK: same architecture
(Guard, Decision, Catalog, Client), same primitives (observe/decideOnly/
recordExecuted/recordWithheld/evaluate), same invariants. Both SDKs speak
the same versioned decide contract (`/v1`, additive-only).

## Cookbook

See [`cookbook/README.md`](./cookbook/README.md) for runnable recipes
proving KIFF stops risky agent actions before they execute.

Each recipe is a **complete, runnable proof**: real models, real agent
frameworks, real side effects, real KIFF runtime. Deploy locally or on
your own infra, run the scenario, see the verdict.

| # | Recipe | Adapter | Verdict |
|---|--------|---------|---------|
| 1 | [duplicate-payment-guard](./cookbook/duplicate-payment-guard/) | OpenClaw (TS) | $100K → $10K, 9 blocked |
| 2 | [refund-ceiling-guard](./cookbook/refund-ceiling-guard/) | LangGraph | $250 → $100, 3 blocked |
| 3 | [collections-promise-guard](./cookbook/collections-promise-guard/) | Agno | 5 contacts → 1, 4 blocked |
| 4 | [chargeback-dispute-guard](./cookbook/chargeback-dispute-guard/) | Strands | $125 → $25, 4 blocked |
| 5 | [vulnerability-escalation-guard](./cookbook/vulnerability-escalation-guard/) | Agno **Teams** | 6 actions → 1, whole team halted by one event |
| 6 | [kyb-verification-guard](./cookbook/kyb-verification-guard/) | Agno **Workflows** | $60 → $12, 4 blocked (once-and-done) |

Recipes 5 and 6 also show **framework guardrails PLUS KIFF**: Agno's
`PIIDetectionGuardrail` (a `pre_hook`, input safety) and KIFF (a
`tool_hook`, action authority) running side by side — different layers,
not competitors.

### Enablement recipes

A second family with the opposite framing: instead of leading with the block,
the agent *does the work* — a real Agno agent performs the legitimate
revenue/ops action (KIFF allows it, state advances), then is declined on every
repeat once state moves on. The boundary is what makes putting the agent on the
task shippable. E2–E5 run on `kiff/kiff v0.6.0` (policy-owned roles) + Agno v2.

| # | Recipe | Adapter | Verdict |
|---|--------|---------|---------|
| E1 | [refund-enablement-guard](./cookbook/refund-enablement-guard/) | Agno | refund issued, 4 repeats declined |
| E2 | [deal-close-enablement-guard](./cookbook/deal-close-enablement-guard/) | Agno | 1 discount, 4 declined (no stacking) |
| E3 | [payment-recovery-enablement-guard](./cookbook/payment-recovery-enablement-guard/) | Agno | 1 charge recovered, 4 declined |
| E4 | [instant-payout-enablement-guard](./cookbook/instant-payout-enablement-guard/) | Agno | 1 payout, 4 declined (one-per-escrow) |
| E5 | [prompt-injection-refund-guard](./cookbook/prompt-injection-refund-guard/) | Agno | adversarial: 0 extra payouts, 2/2 money paths declined |

## License

MIT. See [LICENSE](./LICENSE).
