# Recipe Manifest: kyb-verification-guard

## Complete file inventory

```
kyb-verification-guard/
├── README.md                        # User-facing guide (incl. Guardrails + KIFF)
├── MANIFEST.md                      # This file
├── PROOF.md                         # Live proof record (2026-06-04)
├── .env.example                     # Template for secrets
├── .gitignore
├── requirements.txt                 # Python deps: agno, openai, fastapi
│
├── kiff-decide/                     # Service 1: the KIFF gate (Go)
│   ├── main.go                      # HTTP server: decide, ingest, seed, state
│   ├── domain.go                    # Business: PENDING → VERIFIED
│   └── go.mod                       # Depends on github.com/kiffhq/kiff v0.2.0
│
├── app/
│   └── server.py                    # Service 2: system of record (stdlib only)
│                                    # /business, /verify ($12/check), /ledger, /reset
│
├── agent/
│   └── kyb_workflow.py              # Service 3: Agno WORKFLOW + KIFF guard
│                                    # build_guard(), create_kyb_workflow(), run_workflow()
│                                    # intake → verify (guarded agent) → decision
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
KYB_APP_URL=http://localhost:8082
```

### Build + run
1. `cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide`
2. `python3 app/server.py`
3. `python3 -m venv .venv && source .venv/bin/activate && pip install agno openai fastapi`
4. `cd driver && python3 scenario.py`

## External dependencies

### Go (kiff-decide)
- `github.com/kiffhq/kiff v0.2.0` (public framework, MIT)

### Python (agent)
- `agno>=1.4.0` — agent framework; **Workflows** API + `tool_hooks` middleware
- `openai>=1.0.0` — LLM provider
- `fastapi>=0.110.0` — required by `agno.workflow` (transitive). Without it
  the recipe degrades to running the verify agent directly (same KIFF
  guarantee, no pipeline).
- Agno `PIIDetectionGuardrail` (pre_hook) used when present; optional

### kiff-guard Python SDK
- `src/kiff_guard/` from `packages/python/kiff-guard/` in this repo
- Adapter: `kiff_guard.adapters.agno.agno_hook`

## Reproducibility guarantee

With the files here + prerequisites, anyone can build kiff-decide, run the
Agno workflow + proof driver, and see the same WITHOUT/WITH KIFF verdict,
and verify the gate via `curl http://localhost:8081/v1/entities/{id}/state`.

## What's NOT in the repo (ephemeral)
- `.env` (secrets)
- `kiff-decide/kiff-decide` (compiled binary, rebuild from source)
- `.venv/` (Python virtualenv, recreate from requirements.txt)
- EC2 instance (torn down via 2h TTL)
