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

### How the AWS deploy actually works — the non-obvious parts

This recipe has three pieces that are not obvious from the docs and caused
integration friction. They are documented here so anyone reproducing the deploy
doesn't have to rediscover them.

---

**1. The published `openclaw-sdk` npm package is protocol-incompatible with
recent gateways.**

`openclaw-sdk@2026.3.x` speaks WebSocket protocol 1; current gateway images
(2026.4+) require protocol 3/4. The handshake fails immediately with
`protocol mismatch`. The solution: **bypass the SDK entirely** and speak the
gateway protocol directly with a 50-line raw-WebSocket client (`driver/ocgw.mjs`).

The client uses the documented **trusted same-process backend path**:

```json
{
  "type": "req",
  "method": "connect",
  "params": {
    "minProtocol": 3,  "maxProtocol": 4,
    "client": { "id": "gateway-client", "mode": "backend", "version": "0.1.0", "platform": "node" },
    "role": "operator",
    "scopes": ["operator.read", "operator.write", "operator.approvals", "operator.admin"],
    "auth": { "token": "<OPENCLAW_GATEWAY_TOKEN>" }
  }
}
```

`client.id` must be exactly `"gateway-client"` (not an arbitrary string) and
`client.mode` must be `"backend"`. This path **skips device pairing** and works
on loopback with the shared gateway token. Do not use `clientId: "my-app"` — the
gateway will reject it with "must be equal to one of the allowed values."

The agent-run RPC takes `agentId`, `sessionKey`, `message`, `model`, and
`idempotencyKey` (all four required). It returns immediately with a `runId`;
call `agent.wait({ runId })` to block until done.

---

**2. External plugins cannot be runtime-mounted into the packaged image.**

Three paths that do NOT work:
- `plugins.load.paths: ["/path/to/dist/index.js"]` — ignored by the packaged
  runtime's plugin discovery.
- Mounting the plugin dir at `/app/extensions/<id>` via `-v` — replaces the
  *entire* `/app/extensions` tree, dropping all bundled plugins.
- `openclaw plugins install ./path` — fails on the peer-dep link for `openclaw`
  (the image can't create `node_modules/openclaw` symlinks for user-installed
  plugins).

The solution: **build a derived image** (`openclaw/Dockerfile`) that copies the
plugin into `/app/dist/extensions/<id>` at build time and creates the
`node_modules/openclaw` peer symlink as root before switching to `USER node`.
The baked plugin resolves `openclaw/plugin-sdk/*` from the image's own `/app`.

The peer link:

```dockerfile
RUN ln -sf /app "$EXT/node_modules/openclaw" && chown -R node:node "$EXT"
```

---

**3. The gateway config schema is strict — unknown or wrong-type fields cause a
startup failure.** Key requirements for `ghcr.io/openclaw/openclaw:latest`:

- `models.providers.openai.models` must be an **array of objects** with both
  `id` and `name` — bare strings `["gpt-4o-mini"]` or objects with only `id`
  are rejected.
- `agents.defaults.models["openai/gpt-4o-mini"].agentRuntime.id` must be set
  to `"openclaw"`. Without it, the agent uses the `codex` harness by default and
  fails with `Unknown model: openai-codex/gpt-4o-mini`.
- The `plugins.allow` list must exactly match the plugin manifest `id` field.

Minimal working config:

```json
{
  "models": {
    "providers": {
      "openai": {
        "apiKey": { "source": "env", "provider": "default", "id": "OPENAI_API_KEY" },
        "models": [{ "id": "gpt-4o-mini", "name": "gpt-4o-mini" }]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": { "primary": "openai/gpt-4o-mini" },
      "models": { "openai/gpt-4o-mini": { "agentRuntime": { "id": "openclaw" } } }
    }
  }
}
```

---

**4. The `@kiffhq/kiff-guard` vendor dep is a symlink in development — use
`cp -rL` (dereference) when copying it.**

The plugin's `node_modules/@kiffhq/kiff-guard` resolves via a `file:` reference
in `package.json` and is a symlink in the source tree. `cp -r` follows the
symlink but the relative target breaks once moved. `cp -rL` dereferences it into
real files. The Dockerfile handles this via `COPY vendor/kiff-guard $EXT/...`
from the recipe root.

---

**Verified step order (the one that works, on Amazon Linux 2023 / t3.large):**

```bash
# 1. bootstrap (via EC2 user-data or manually):
dnf install -y docker git && systemctl enable --now docker && usermod -aG docker ec2-user
# install Go 1.23 and Node 22 from their official sources

# 2. build kiff-decide (do this AFTER bootstrap, before OpenClaw):
cd kiff-decide && go build -o kiff-decide .   # fetches github.com/kiffhq/kiff v0.2.0

# 3. start core services (detached, before OpenClaw):
bash start-core.sh    # kiff-decide on :8081, ap-app on :8082

# 4. pull + build the derived OpenClaw image:
docker pull ghcr.io/openclaw/openclaw:latest
docker build -t kiff-cookbook-openclaw:local -f openclaw/Dockerfile .

# 5. run the gateway (host network, so it reaches :8081 and :8082):
bash start-openclaw.sh    # waits for /healthz, exits when HEALTHY

# 6. install driver deps + run scenario:
cd driver && npm install ws
node scenario.mjs
```

The `start-core.sh` and `start-openclaw.sh` scripts handle all of this; the
breakdown above is for debugging or adapting to different infra.

---



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
