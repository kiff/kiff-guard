# Recipe Manifest: duplicate-payment-guard

This file documents **everything** needed to reproduce the recipe from scratch.

## Complete file inventory

```
duplicate-payment-guard/
├── README.md                           # User-facing guide
├── MANIFEST.md                         # This file (completeness checklist)
├── .env.example                        # Template for secrets
├── .gitignore                          # Excludes .env, binaries, node_modules
│
├── kiff-decide/                        # Service 1: the KIFF gate (Go)
│   ├── main.go                         # HTTP server: decide, ingest, seed, state
│   ├── domain.go                       # Payments domain: Invoice PENDING→PAID
│   └── go.mod                          # Depends on github.com/kiffhq/kiff v0.2.0
│
├── ap-app/                             # Service 2: system of record (Node)
│   └── server.js                       # /pay, /ledger, /reset (stdlib only, no deps)
│
├── openclaw/                           # Service 3: OpenClaw gateway config + Dockerfile
│   ├── Dockerfile                      # Derives from ghcr.io/openclaw/openclaw:latest, bakes plugin
│   ├── openclaw.json                   # Gateway config: openai provider, plugins.allow
│   ├── extension.package.json          # Minimal package.json for baked plugin
│   └── openclaw.plugin.json            # Plugin manifest: pay_invoice + before_tool_call
│
├── openclaw-plugin/                    # The kiff-guard-demo plugin source
│   ├── src/index.ts                    # definePluginEntry: tool + hook
│   ├── package.json                    # Vendors @kiffhq/kiff-guard from ../vendor
│   ├── openclaw.plugin.json            # Manifest (synced to openclaw/)
│   └── tsconfig.json                   # NodeNext, outDir: ./dist
│
├── vendor/                             # Vendored dependencies
│   └── kiff-guard/                     # @kiffhq/kiff-guard v0.1.0 (TypeScript SDK)
│       ├── package.json                # Exports: . and ./adapters/openclaw
│       └── dist/                       # Compiled JS + .d.ts (self-contained)
│           ├── index.js, index.d.ts
│           ├── client.js, decision.js, catalog.js, guard.js, draft.js
│           └── adapters/openclaw.js, openclaw.d.ts
│
├── driver/                             # Proof scripts
│   ├── ocgw.mjs                        # Raw-WS gateway client (protocol 3/4)
│   ├── gate_proof.mjs                  # Gate+app proof (no OpenClaw)
│   ├── scenario.mjs                    # Full end-to-end proof (real agent)
│   ├── agent_wait_probe.mjs            # Working agent-run RPC reference
│   ├── rpc_discover.mjs                # RPC discovery helper
│   ├── tool_probe.mjs                  # Tool invocation discovery
│   ├── invoke_shape.mjs                # tools.invoke param discovery
│   ├── agent_probe.mjs                 # Agent RPC probe
│   ├── connect_check.mjs               # Gateway connection test
│   └── handshake_test.mjs              # Protocol handshake test
│
├── start-core.sh                       # Starts kiff-decide + ap-app
└── start-openclaw.sh                   # Builds derived image + runs gateway
```

## What someone needs to run this

### Prerequisites
- **Go 1.23+** (to build kiff-decide)
- **Node 22+** (to run ap-app, build plugin, run drivers)
- **Docker 25+** (to build + run the derived OpenClaw image)
- **OpenAI API key** (for the real agent turn)
- **Network**: all three services on localhost (or adapt to Docker Compose)

### Secrets (not in repo)
- `.env` (create from `.env.example`):
  ```
  OPENAI_API_KEY=sk-proj-...
  OPENCLAW_GATEWAY_TOKEN=<random-hex-32>
  KIFF_COOKBOOK_MODEL=openai/gpt-4o-mini
  ```

### Build steps
1. **kiff-decide**: `cd kiff-decide && go build -o kiff-decide .`
2. **openclaw-plugin**: `cd openclaw-plugin && npm install && npm run build`
3. **openclaw image**: `docker build -t kiff-cookbook-openclaw:local -f openclaw/Dockerfile .`

### Run steps
1. `./start-core.sh` (kiff-decide on :8081, ap-app on :8082)
2. `./start-openclaw.sh` (gateway on :18789)
3. `cd driver && node scenario.mjs` (the proof)

### What gets proven
- **WITHOUT KIFF**: 10 retries → $100,000 / 10 debits
- **WITH KIFF**: 1 agent turn (gpt-4o-mini) → KIFF allows (PENDING) → debit → state advances (PAID) → 9 retries blocked → $10,000 / 1 debit

## External dependencies (fetched at build time)

### Go (kiff-decide)
- `github.com/kiffhq/kiff v0.2.0` (public framework, MIT)

### Node (openclaw-plugin)
- `@kiffhq/kiff-guard` (vendored in `vendor/kiff-guard/`, MIT)
- `openclaw` peer (resolved via symlink to /app in the derived image)
- `typescript` (devDep, for `npm run build`)

### Docker (openclaw)
- Base image: `ghcr.io/openclaw/openclaw:latest` (public, as of 2026-05-30)

## Verification checklist

Before tearing down the EC2 box, confirm:
- [x] All source files synced to workspace
- [x] go.mod present (framework v0.2.0 dependency)
- [x] Vendored kiff-guard SDK present (dist/ compiled)
- [x] Dockerfile + all config files present
- [x] All driver scripts present
- [x] README written
- [x] MANIFEST written
- [x] Proof passed on EC2 (exit 0, correct ledger output)

## What's NOT in the repo (ephemeral)
- `.env` (secrets)
- `kiff-decide/kiff-decide` (compiled binary)
- `openclaw-plugin/dist/` (compiled plugin, rebuilt from src)
- `openclaw-plugin/node_modules/` (npm install)
- Docker image `kiff-cookbook-openclaw:local` (rebuilt from Dockerfile)
- EC2 instance + security group + key pair (torn down after proof)

## Reproducibility guarantee

With the files in this directory + the prerequisites above, anyone can:
1. Build all three services
2. Run the proof locally or on their own infra
3. See the same WITHOUT/WITH KIFF verdict
4. Verify the gate themselves (curl the state endpoint, read the ledger)

The recipe is **complete and self-contained**.
