# duplicate-payment-guard

A complete, runnable cookbook recipe proving KIFF stops a duplicate-payment
retry storm with a real OpenClaw agent + real OpenAI model.

## The scenario

An AP agent pays a $10,000 invoice. A flaky connection drops the success
response → the transport retries ~10 times → each retry would debit again
($100,000 risk). **KIFF blocks the retries** because the invoice is now PAID
(`state_not_allowed`). Each individual call is legitimate; only a
state-aware gate stops the emergent repeat.

## Architecture (3 microservices)

1. **kiff-decide** (Go): the KIFF gate. Wraps the real `github.com/kiffhq/kiff`
   v0.2.0 runtime with a tiny payments domain (Invoice: PENDING → PAID).
   Exposes the decide contract the guard SDK calls.
2. **ap-app** (Node): the system of record. Holds invoices + ledger. `/pay` is
   deliberately NON-idempotent (the honest baseline: a duplicate /pay WILL
   debit again). After a real debit, tells the gate to advance the invoice to
   PAID.
3. **openclaw** (Docker): the OpenClaw gateway (`ghcr.io/openclaw/openclaw:latest`)
   with a baked `kiff-guard-demo` plugin. The plugin registers `pay_invoice`
   (calls ap-app /pay) AND a `before_tool_call` hook (from
   `@kiffhq/kiff-guard/adapters/openclaw`) in ENFORCE mode. Before any tool
   runs, KIFF decides.

## Prerequisites

- AWS CLI configured (or adapt to local Docker Compose)
- OpenAI API key
- Go 1.23+, Node 22+, Docker 25+

## Deploy to AWS EC2 (throwaway box)

The recipe includes a one-command deploy script that provisions a t3.large EC2
instance, installs dependencies, builds all three services, and runs the proof.

```bash
cd .cookbook-build/duplicate-payment-guard
export OPENAI_API_KEY="sk-proj-..."
./deploy-aws.sh
```

The script:
- Creates a throwaway EC2 instance (t3.large, 30GB, us-east-1)
- Locks SSH + gateway port to your IP
- Installs Docker, Go, Node
- Builds kiff-decide (Go binary against public framework v0.2.0)
- Builds the derived OpenClaw image with the baked plugin
- Runs the full scenario
- Prints the proof
- **Tears down the instance + rotates the OpenAI key**

## Manual deploy (local or custom infra)

### 1. Start core services

```bash
# Terminal 1: kiff-decide
cd kiff-decide
go build -o kiff-decide .
./kiff-decide -addr=:8081

# Terminal 2: ap-app
cd ap-app
node server.js  # listens on :8082
```

### 2. Build + start OpenClaw with the baked plugin

```bash
# Set env vars
export OPENAI_API_KEY="sk-proj-..."
export OPENCLAW_GATEWAY_TOKEN="$(openssl rand -hex 32)"
echo "$OPENCLAW_GATEWAY_TOKEN" > .env

# Build the derived image (plugin baked into /app/dist/extensions)
docker build -t kiff-cookbook-openclaw:local -f openclaw/Dockerfile .

# Run the gateway
./start-openclaw.sh
```

The gateway runs on `:18789` (host network mode so it can reach kiff-decide
and ap-app on localhost).

### 3. Run the proof

```bash
cd driver
export OPENCLAW_GATEWAY_TOKEN="$(cat ../.env | grep OPENCLAW_GATEWAY_TOKEN | cut -d= -f2)"
node scenario.mjs
```

Expected output:

```
==================================================================
  WITHOUT KIFF — ungoverned: every retry debits
==================================================================
flaky connection: the $10,000 payment 'fails' to ack and retries 10x...
  attempt 1: ap-app debited (#1)
  ...
  attempt 10: ap-app debited (#10)

  RESULT: $100000.00 paid across 10 debits.

==================================================================
  WITH KIFF — the gate stops the duplicates
==================================================================
agent (real openai/gpt-4o-mini) is asked to pay invoice inv-kiff-... ($10,000)...
  first attempt via the agent: EXECUTED (KIFF allowed, invoice PENDING)
flaky connection: retrying the same tool call 9x...
  retry 2: blocked by KIFF (... state "PAID" ...)
  ...
  retry 10: blocked by KIFF (... state "PAID" ...)

  RESULT: $10000.00 paid across 1 debit(s); 9 retries blocked by KIFF.

==================================================================
  VERDICT
==================================================================
  WITHOUT KIFF : $100000.00  (10 debits)   FAIL
  WITH KIFF    : $10000.00  (1 debit)    PASS

  PROOF: every individual $10k call was legitimate. Only a state-aware gate stopped the repeat.
```

## What's being proven

1. **The gate + app loop works** (`driver/gate_proof.mjs`): WITHOUT KIFF = N
   debits; WITH KIFF = 1 debit, N-1 blocked. No OpenClaw, just the gate +
   ap-app.
2. **The full integration works** (`driver/scenario.mjs`): a REAL agent
   (gpt-4o-mini) calls the guarded tool → KIFF allows (PENDING) → debit →
   state advances → retries blocked (PAID). The model, the plugin, the hook,
   the guard SDK, the gate, and the app all work together.

## Files

```
duplicate-payment-guard/
├── README.md                   this file
├── kiff-decide/                the KIFF gate (Go)
│   ├── main.go                 HTTP server: /v1/proposals/decide, /v1/events/raw, /seed
│   ├── domain.go               payments domain: Invoice PENDING→PAID, PAY_INVOICE allowed only in PENDING
│   └── go.mod                  depends on github.com/kiffhq/kiff v0.2.0
├── ap-app/
│   └── server.js               system of record (Node stdlib only): /pay, /ledger, /reset
├── openclaw/
│   ├── Dockerfile              derived image: bakes kiff-guard-demo into /app/dist/extensions
│   ├── openclaw.json           gateway config: openai provider, agentRuntime.id=openclaw, plugins.allow=[kiff-guard-demo]
│   ├── extension.package.json  minimal package.json for the baked plugin
│   └── openclaw.plugin.json    plugin manifest: pay_invoice tool + before_tool_call hook
├── openclaw-plugin/            the plugin source (TypeScript)
│   ├── src/index.ts            definePluginEntry: pay_invoice tool + kiffBeforeToolCall(guard) hook
│   ├── package.json            vendors @kiffhq/kiff-guard from ../vendor/kiff-guard
│   └── tsconfig.json
├── vendor/
│   └── kiff-guard/             the kiff-guard-js SDK (self-contained, no openclaw runtime dep)
├── driver/                     proof scripts
│   ├── ocgw.mjs                raw-WS gateway client (protocol 3/4, operator.admin scope)
│   ├── gate_proof.mjs          gate+app proof (no OpenClaw)
│   ├── scenario.mjs            full end-to-end proof (real agent + model)
│   └── agent_wait_probe.mjs    working agent-run RPC reference
├── start-core.sh               starts kiff-decide + ap-app
├── start-openclaw.sh           builds derived image + runs gateway
└── deploy-aws.sh               one-command EC2 deploy + proof + teardown
```

## Trust but verify

The recipe is designed for a skeptical developer who wants to see the proof
themselves:

1. **One command** → everything ready
2. **See WITHOUT-vs-WITH KIFF side by side** → the ledger proves it
3. **Verify the gate yourself** → `curl http://localhost:8081/v1/entities/inv-001/state`
   shows the state; `driver/gate_proof.mjs` proves the gate+app loop without
   OpenClaw; the full scenario proves the model+plugin+gate path.

## Security notes

- The standalone kiff-decide server ignores auth (single-tenant, local-only).
  The cloud's multi-tenant API (`api.kiff.dev`) enforces roles from the
  authenticated key.
- The OpenAI key is passed as an env var. **Rotate it after testing** (it's in
  the transcript = compromised).
- The EC2 deploy uses root credentials for simplicity. Production deploys
  should use IAM roles + least-privilege policies.

## What's next

This is recipe #1. Future recipes:
- **Insurance settlement audit** (the $10M court case: "show me the LLM's
  reasoning")
- **Multi-agent coordination** (two agents, one resource, KIFF arbitrates)
- **Approval-required actions** (high-risk transfers need human clearance)

## License

MIT (framework + guard SDK). The recipe is a reference implementation.
