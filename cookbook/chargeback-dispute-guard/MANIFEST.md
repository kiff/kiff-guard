# Recipe Manifest: chargeback-dispute-guard

## File inventory

```
chargeback-dispute-guard/
├── README.md, PROOF.md, MANIFEST.md, .env.example, requirements.txt
├── kiff-decide/   domain.go, main.go, go.mod
├── app/           server.py
├── agent/         disputes_agent.py
└── driver/        scenario.py
```

## Prerequisites
- Go 1.23+, Python 3.9+, OpenAI API key

## Build + Run
```bash
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide &
python3 app/server.py &
python3 -m venv .venv && source .venv/bin/activate
pip install strands-agents strands-agents-tools openai
cd driver && python3 scenario.py
```

## External dependencies
- `github.com/kiffhq/kiff v0.2.0`
- `strands-agents`, `strands-agents-tools`, `openai`
- kiff-guard Python SDK + strands adapter
