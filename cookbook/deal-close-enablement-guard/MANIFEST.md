# Recipe Manifest: deal-close-enablement-guard

## Complete file inventory

```
deal-close-enablement-guard/
├── README.md                        # User-facing guide
├── MANIFEST.md                      # This file
├── PROOF.md                         # Live proof record
├── .env.example                     # Template for secrets
├── .gitignore                       # Excludes .env, .venv, built binary
├── requirements.txt                 # Python deps: agno, openai, boto3
│
├── kiff-decide/                     # Service 1: the KIFF gate (Go)
│   ├── main.go                      # HTTP server: decide, ingest, seed, state
│   ├── domain.go                    # Deal domain: CREATED→OPEN→DISCOUNTED; APPLY_DISCOUNT from OPEN
│   │                                # policy-owned roles: AssignRole(deal-agent, sales)
│   ├── go.mod                       # Depends on github.com/kiff/kiff v0.6.0
│   └── go.sum
│
├── app/
│   └── server.py                    # Service 2: deal-app, system of record (stdlib only)
│                                    # /deal, /qualify, /discount, /ledger, /reset, /healthz
│                                    # non-idempotent /discount (stacks on every call)
│                                    # port via APP_PORT (default 8082)
│
├── agent/
│   └── deal_agent.py                # Service 3: Agno (v2) agent + KIFF guard
│                                    # build_guard(), create_deal_agent(), run_agent(), make_model()
│                                    # tool: apply_discount(deal_id, percent, reason)
│
└── driver/
    └── scenario.py                  # Proof: WITHOUT vs WITH KIFF, real LLM in loop
```

## What someone needs to run this

### Prerequisites
- Go 1.23+
- Python 3.9+
- OpenAI API key (default) or AWS credentials (Bedrock)

### Secrets / configuration
```
MODEL_PROVIDER=openai              # openai (default) | bedrock
MODEL_ID=                          # optional override per provider
OPENAI_API_KEY=sk-proj-...         # for MODEL_PROVIDER=openai
AWS_ACCESS_KEY_ID=                 # for MODEL_PROVIDER=bedrock
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
KIFF_CLOUD_API_KEY=kiff_live_...   # optional: KIFF Cloud dashboard
KIFF_CLOUD_URL=https://api.kiff.dev
KIFF_BASE_URL=http://localhost:8081
DEAL_APP_URL=http://localhost:8082
APP_PORT=8082                      # optional: override the app's listen port
```

### Build steps
1. `cd kiff-decide && go mod tidy && go build -o kiff-decide .`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`

### Run steps
1. `./kiff-decide/kiff-decide -addr=:8081`
2. `python3 app/server.py`
3. `python3 driver/scenario.py`

## External dependencies

### Go (kiff-decide)
- `github.com/kiff/kiff v0.6.0` (public framework, MIT; policy-owned roles via AssignRole)

### Python (agent)
- `agno>=2.6,<3` — agent framework (v2) with `tool_hooks` middleware
- `openai>=1.0.0` — default LLM provider
- `boto3>=1.34.0` — AWS Bedrock provider (optional)

### kiff-guard Python SDK
- `src/kiff_guard/` from `packages/python/kiff-guard/` in this repo
- Adapter: `kiff_guard.adapters.agno.agno_hook`

## Reproducibility guarantee

With the files in this directory + prerequisites above, anyone can:
1. Build kiff-decide (Go binary against public framework)
2. Run the Python agent and proof driver
3. See the same enablement verdict: the agent applies the legitimate closing
   discount (allowed), the deal advances to DISCOUNTED, and every repeat is
   declined (no stacking)
4. Verify the gate via `curl http://localhost:8081/v1/entities/{id}/state`

## What's NOT in the repo (ephemeral)
- `.env` (secrets)
- `kiff-decide/kiff-decide` (compiled binary, rebuild from source)
- `.venv/` and `__pycache__/` (recreate from requirements.txt)
