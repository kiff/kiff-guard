# Proof Record: duplicate-payment-guard

**Date**: 2026-06-01  
**Instance**: EC2 t3.large, us-east-1 (ephemeral, torn down after proof)  
**Framework**: github.com/kiffhq/kiff v0.2.0 (public, MIT)  
**Guard SDK**: @kiffhq/kiff-guard v0.1.0 (TypeScript, MIT)  
**Gateway**: ghcr.io/openclaw/openclaw:latest (2026-05-28)  
**Model**: OpenAI gpt-4o-mini  

## What was proven

A complete end-to-end integration of KIFF stopping a duplicate-payment retry
storm with:
- A **real OpenAI model** (gpt-4o-mini)
- A **real agent framework** (OpenClaw gateway)
- A **real KIFF runtime** (public framework v0.2.0)
- A **real guard SDK** (kiff-guard-js with OpenClaw adapter)
- A **real system of record** (ap-app, deliberately non-idempotent)

## The scenario

An AP agent pays a $10,000 invoice. A flaky connection drops the success
response → the transport retries 10 times. Each retry is a legitimate call
(same invoice id, same amount), but only the FIRST should debit.

## Results (verified live on EC2)

### WITHOUT KIFF (ungoverned baseline)
```
flaky connection: the $10,000 payment 'fails' to ack and retries 10x...
  attempt 1: ap-app debited (#1)
  attempt 2: ap-app debited (#2)
  ...
  attempt 10: ap-app debited (#10)

RESULT: $100000.00 paid across 10 debits.
```

### WITH KIFF (state-aware gate)
```
agent (real openai/gpt-4o-mini) is asked to pay invoice inv-kiff-... ($10,000)...
  first attempt via the agent: EXECUTED (KIFF allowed, invoice PENDING)
flaky connection: retrying the same tool call 9x...
  retry 2: blocked by KIFF (... entity is in state "PAID" ...)
  retry 3: blocked by KIFF (... entity is in state "PAID" ...)
  ...
  retry 10: blocked by KIFF (... entity is in state "PAID" ...)

RESULT: $10000.00 paid across 1 debit(s); 9 retries blocked by KIFF.
```

### Verdict
```
WITHOUT KIFF : $100000.00  (10 debits)   FAIL
WITH KIFF    : $10000.00  (1 debit)    PASS

PROOF: every individual $10k call was legitimate. Only a state-aware gate
stopped the repeat.
```

Exit code: 0 (proof passed)

## What the proof shows

1. **The gate works**: kiff-decide (wrapping the public framework v0.2.0)
   correctly evaluates PAY_INVOICE against the Invoice state machine:
   - PENDING → allowed
   - PAID → blocked (state_not_allowed)

2. **The integration works**: the OpenClaw `before_tool_call` hook →
   kiff-guard-js adapter → HTTP client → kiff-decide gate → framework
   runtime → domain validation. The full stack, end to end.

3. **The model works**: a real gpt-4o-mini turn called the `pay_invoice` tool
   (not a mock, not a stub — a real OpenAI API call with a real agent
   framework).

4. **The state machine is honest**: the invoice only advances to PAID after a
   REAL debit (ap-app calls `/v1/events/raw` to ingest INVOICE_PAID). The
   state doesn't advance on a blocked retry, so the gate's decision is
   grounded in real side effects.

5. **The recipe is reproducible**: all source files, configs, and build steps
   are captured in this directory. Anyone with Go + Node + Docker + an OpenAI
   key can run the same proof and see the same verdict.

## Architecture verified

```
┌─────────────────────────────────────────────────────────────────┐
│  OpenClaw Gateway (Docker, :18789)                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  kiff-guard-demo plugin (baked into image)                 │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  before_tool_call hook (kiff-guard-js adapter)       │  │ │
│  │  │  ↓                                                    │  │ │
│  │  │  HTTPClient → POST /v1/proposals/decide              │  │ │
│  │  │              → kiff-decide:8081                       │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  pay_invoice tool (if KIFF allows)                   │  │ │
│  │  │  ↓                                                    │  │ │
│  │  │  fetch → POST /pay → ap-app:8082                     │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         ↓ (if allowed)                    ↓ (after real debit)
┌──────────────────────┐          ┌──────────────────────────────┐
│  ap-app (Node :8082) │          │  kiff-decide (Go :8081)      │
│  - /pay (debit)      │ ←────────│  - /v1/proposals/decide      │
│  - /ledger (proof)   │  ingest  │  - /v1/events/raw (ingest)   │
│  - /reset            │  PAID    │  - /seed (PENDING)           │
└──────────────────────┘          │  - /v1/entities/{id}/state   │
                                  │                              │
                                  │  Wraps:                      │
                                  │  github.com/kiffhq/kiff      │
                                  │  v0.2.0 (public framework)   │
                                  └──────────────────────────────┘
```

## Key integration points verified

1. **OpenClaw plugin discovery**: the baked plugin at
   `/app/dist/extensions/kiff-guard-demo/` was discovered by the runtime's
   filesystem scan (derived index).

2. **Peer dependency resolution**: the plugin's `import { definePluginEntry }
   from "openclaw/plugin-sdk/plugin-entry"` resolved via the symlinked
   `node_modules/openclaw → /app` peer link.

3. **Vendored SDK resolution**: the plugin's `import { Guard, HTTPClient,
   ToolMap } from "@kiffhq/kiff-guard"` resolved via the baked
   `node_modules/@kiffhq/kiff-guard/` (self-contained, no openclaw runtime
   dep).

4. **Hook registration**: the `before_tool_call` hook registered by
   `api.on("before_tool_call", kiffBeforeToolCall(guard), { priority: 50 })`
   was active (verified via `openclaw plugins inspect kiff-guard-demo
   --runtime --json` showing `hookCount: 1`).

5. **Tool registration**: the `pay_invoice` tool registered by
   `api.registerTool(...)` appeared in `tools.effective` output (plugin group,
   3 tools total including pay_invoice).

6. **RPC contract**: the gateway's `tools.invoke` RPC (params: `{ name, args,
   sessionKey, agentId }`) passed through the hook → KIFF → returned
   `{ ok: false, error: { code: "forbidden", message: "KIFF withheld..." } }`
   on blocked calls.

7. **Agent runtime**: the `agentRuntime.id: "openclaw"` config (required by
   latest gateway schema) was set, and the agent turn completed successfully
   (status: ok, livenessState: working).

8. **State machine**: the Invoice state machine (PENDING → PAID via
   INVOICE_PAID event) was enforced by the framework runtime, and the
   PAY_INVOICE action contract's `AllowedStates: [PENDING]` was respected.

## Files that prove it

- `driver/scenario.mjs`: the full proof script (exit 0 = passed)
- `driver/gate_proof.mjs`: gate+app proof without OpenClaw (also passed)
- `kiff-decide/domain.go`: the state machine definition
- `openclaw-plugin/src/index.ts`: the plugin that wires it all together
- `vendor/kiff-guard/dist/adapters/openclaw.js`: the adapter that speaks the
  hook contract

## Teardown checklist

Before terminating the EC2 instance:
- [x] Proof passed (exit 0, correct ledger output)
- [x] All source files synced to workspace
- [x] README + MANIFEST + PROOF written
- [x] Vendored SDK synced
- [x] go.mod synced
- [ ] EC2 instance terminated
- [ ] Security group deleted
- [ ] Key pair deleted
- [ ] OpenAI key rotated (it's in the transcript = compromised)

## What's next

This is recipe #1 in the KIFF cookbook. It proves the framework + guard SDK +
agent integration works end-to-end with a real model and a real side effect.

Future recipes:
- **Insurance settlement audit** (the $10M court case: "show me the LLM's
  reasoning" — the AUDIT story)
- **Multi-agent coordination** (two agents, one resource, KIFF arbitrates)
- **Approval-required actions** (high-risk transfers need human clearance)

The recipe is **complete, reproducible, and proven**.
