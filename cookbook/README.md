# KIFF Cookbook

Real-world recipes proving KIFF stops risky agent actions before they execute.

Each recipe is a **complete, runnable proof**: real models, real agent frameworks, real side effects, real KIFF runtime. Deploy locally or on your own infra, run the scenario, see the verdict.

## Recipes

### 1. [duplicate-payment-guard](./duplicate-payment-guard/)

**The problem**: An AP agent pays a $10,000 invoice. A flaky connection drops the success response → the transport retries 10 times → each retry would debit again ($100,000 risk).

**The proof**: KIFF blocks the retries because the invoice is now PAID (`state_not_allowed`). Each individual call is legitimate; only a state-aware gate stops the emergent repeat.

**What's proven**:
- Real OpenAI model (gpt-4o-mini)
- Real agent framework (OpenClaw gateway)
- Real KIFF runtime (public framework v0.2.0)
- Real guard SDK (kiff-guard-js with OpenClaw adapter)
- Real system of record (deliberately non-idempotent)

**Verdict**: WITHOUT KIFF = $100,000 / 10 debits; WITH KIFF = $10,000 / 1 debit, 9 blocked.

**Architecture**: 3 microservices (kiff-decide gate, ap-app system-of-record, openclaw gateway with baked plugin). Deploys to EC2 or runs locally.

---

## What makes a cookbook recipe

1. **Complete**: all source code, configs, build steps, and dependencies included
2. **Runnable**: one command → everything ready → see the proof
3. **Honest**: real models, real frameworks, real side effects (no mocks)
4. **Reproducible**: anyone with the prerequisites can run it and see the same verdict
5. **Verifiable**: the ledger/audit trail proves what happened

## Prerequisites (typical)

- Go 1.23+ (for kiff-decide gate)
- Node 22+ (for drivers, some systems-of-record)
- Docker 25+ (for agent frameworks)
- Model API key (OpenAI, Anthropic, etc.)

## How to use a recipe

```bash
cd cookbook/<recipe-name>
# 1. Read the README (scenario, architecture, what's proven)
# 2. Set secrets in .env (from .env.example)
# 3. Build: ./build.sh or follow the README steps
# 4. Run: ./run.sh or node driver/scenario.mjs
# 5. Verify: check the ledger, curl the state endpoint, read the logs
```

## Coming soon

- **Insurance settlement audit** (the $10M court case: "show me the LLM's reasoning")
- **Multi-agent coordination** (two agents, one resource, KIFF arbitrates)
- **Approval-required actions** (high-risk transfers need human clearance)

## Why cookbook recipes matter

Agent frameworks give you tools, hooks, and guardrails. KIFF gives you a **state machine** that knows what's allowed *right now* based on what already happened. The cookbook proves the two work together to stop emergent risks that no single-call guardrail can catch.

## License

MIT (framework + guard SDK). Recipes are reference implementations.
