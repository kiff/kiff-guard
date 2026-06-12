# Recipe Manifest: refund-ceiling-guard

## Complete file inventory

```
refund-ceiling-guard/
├── README.md                     # User-facing guide
├── MANIFEST.md                   # This file
├── PROOF.md                      # Live proof record (2026-06-03)
├── .env.example                  # Template for secrets
├── requirements.txt              # Python deps: langchain, langchain-openai, langgraph
│
├── kiff-decide/                  # Service 1: the KIFF gate (Go)
│   ├── main.go                   # HTTP server: decide, ingest, seed, state
│   ├── domain.go                 # Order domain: PAID→PARTIALLY_REFUNDED→FULLY_REFUNDED
│   └── go.mod                    # Depends on github.com/kiffhq/kiff v0.2.0
│
├── app/
│   └── server.py                 # Service 2: system of record (stdlib only)
│                                 # /order, /refund (non-idempotent), /ledger, /reset
│
├── agent/
│   └── refund_agent.py          # Service 3: LangGraph agent + KIFF guard
│                                 # build_guard(), create_refund_agent(), run_agent()
│
└── driver/
    └── scenario.py               # Proof: WITHOUT vs WITH KIFF, real LLM in loop
```

## What someone needs to run this

### Prerequisites
- Go 1.23+
- Python 3.9+
- OpenAI API key

### Secrets
```
OPENAI_API_KEY=sk-proj-...
KIFF_CLOUD_API_KEY=kiff_live_...   # optional
KIFF_CLOUD_URL=https://api.kiff.dev
KIFF_BASE_URL=http://localhost:8081
REFUND_APP_URL=http://localhost:8082
```

### Build + Run
```bash
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide &
python3 app/server.py &
python3 -m venv .venv && source .venv/bin/activate
pip install langchain langchain-openai langgraph
cd driver && python3 scenario.py
```

## External dependencies

### Go
- `github.com/kiffhq/kiff v0.2.0`

### Python
- `langchain>=0.3.0`, `langchain-openai>=0.3.0`, `langgraph>=0.4.0`
- kiff-guard Python SDK + adapters from `packages/python/kiff-guard/`
