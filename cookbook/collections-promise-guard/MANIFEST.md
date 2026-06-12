# Recipe Manifest: collections-promise-guard

## Complete file inventory

```
collections-promise-guard/
├── README.md                        # User-facing guide
├── MANIFEST.md                      # This file
├── PROOF.md                         # Live proof record (2026-06-03)
├── .env.example                     # Template for secrets
├── requirements.txt                 # Python deps: agno, openai
│
├── kiff-decide/                     # Service 1: the KIFF gate (Go)
│   ├── main.go                      # HTTP server: decide, ingest, seed, state
│   ├── domain.go                    # Collections domain: DELINQUENT→PROMISE_ACTIVE→FULFILLED|BROKEN
│   └── go.mod                       # Depends on github.com/kiffhq/kiff v0.2.0
│
├── app/
│   └── server.py                    # Service 2: system of record (stdlib only)
│                                    # /contact, /promise, /case, /ledger, /reset
│
├── agent/
│   └── collections_agent.py        # Service 3: Agno agent + KIFF guard
│                                    # build_guard(), create_collections_agent(), run_agent()
│
└── driver/
    └── scenario.py                  # Proof: WITHOUT vs WITH KIFF, real LLM in loop
```

## What someone needs to run this

### Prerequisites
- Go 1.23+
- Python 3.9+
- OpenAI API key

### Secrets
```
OPENAI_API_KEY=sk-proj-...
KIFF_CLOUD_API_KEY=kiff_live_...   # optional: KIFF Cloud dashboard
KIFF_CLOUD_URL=https://api.kiff.dev
KIFF_BASE_URL=http://localhost:8081
COLLECTIONS_APP_URL=http://localhost:8082
```

### Build steps
1. `cd kiff-decide && go mod tidy && go build -o kiff-decide .`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install agno openai`

### Run steps
1. `./kiff-decide/kiff-decide -addr=:8081`
2. `python3 app/server.py`
3. `cd driver && python3 scenario.py`

## External dependencies

### Go (kiff-decide)
- `github.com/kiffhq/kiff v0.2.0` (public framework, MIT)

### Python (agent)
- `agno>=1.4.0` — agent framework with `tool_hooks` middleware
- `openai>=1.0.0` — LLM provider

### kiff-guard Python SDK
- `src/kiff_guard/` from `packages/python/kiff-guard/` in this repo
- Adapter: `kiff_guard.adapters.agno.agno_hook`

## Reproducibility guarantee

With the files in this directory + prerequisites above, anyone can:
1. Build kiff-decide (Go binary against public framework)
2. Run the Python agent and proof driver
3. See the same WITHOUT/WITH KIFF verdict
4. Verify the gate themselves via `curl http://localhost:8081/v1/entities/{id}/state`

## What's NOT in the repo (ephemeral)
- `.env` (secrets)
- `kiff-decide/kiff-decide` (compiled binary, rebuild from source)
- `.venv/` (Python virtualenv, recreate from requirements.txt)
- EC2 instance (torn down via 2h TTL)
