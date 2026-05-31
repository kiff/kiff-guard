# kiff-guard

**Drop-in KIFF clearance for any agent's tool calls.** One guard, two modes:

- **observe** — runs every tool, records an audit trail, and learns the
  action catalog. No KIFF account, no domain, no API call required. The
  fastest way to see what your agents actually do.
- **enforce** — asks KIFF to decide *before* each tool runs: `allowed`
  proceeds, anything else (`approval_required` / `blocked` / `invalid` /
  any future outcome) withholds. Fail-safe by construction.

The same one-line integration that governs your agent at runtime also
**derives a starter KIFF domain** from real traffic — so you never start
from a blank policy file.

> Part of [KIFF](https://kiff.dev) — air traffic control for AI agents.
> This repo is the **client SDK + framework adapters**, MIT-licensed and
> community-maintainable. The framework lives at
> [`kiffhq/kiff`](https://github.com/kiffhq/kiff); the hosted runtime is
> KIFF Cloud.

## Repository layout

```
packages/
  python/kiff-guard/   # the Python SDK (shipped): core + 9 adapters
  js/                  # the TypeScript SDK (planned — see below)
```

The guard is a **framework-agnostic core** plus **thin adapters**, one
per agent framework, each translating that framework's pre-tool-execution
seam into a single call to the core. The guard logic lives once; an
adapter adds no governance logic of its own.

## Python SDK

See [`packages/python/kiff-guard/README.md`](./packages/python/kiff-guard/README.md)
for install, quickstart, and per-framework usage.

```bash
pip install kiff-guard            # core, zero deps
pip install "kiff-guard[agno]"    # + a framework adapter's deps
```

```python
from kiff_guard import Guard
from kiff_guard.adapters.agno import agno_hook

guard = Guard(mode="observe")     # zero-config audit; no KIFF account
agent = Agent(model=..., tools=[...], tool_hooks=[agno_hook(guard)])
```

## Adapters

| Framework | Lang | Shape | Status |
|---|---|---|---|
| Agno | py | middleware (`tool_hooks`) | shipped |
| LangGraph / LangChain | py | middleware (`wrap_tool_call`) | shipped |
| Hermes (Nous) | py | vote (`pre_tool_call` plugin hook) | shipped |
| OpenAI Agents SDK | py | vote (tool input guardrail) | shipped |
| Google ADK | py | vote (`before_tool_callback`) | shipped |
| Pydantic AI | py | vote (`before_tool_execute` hook) | shipped |
| Strands Agents | py | vote (`BeforeToolCallEvent`) | shipped |
| Haystack Agents | py | vote (`ConfirmationStrategy`) | shipped |
| Microsoft Agent Framework | py | middleware (`FunctionMiddleware`, async) | shipped |
| OpenClaw | **ts** | vote (`before_tool_call`) | planned (needs the JS SDK) |
| LlamaIndex | py | — | planned |

Two integration shapes: **middleware** (the guard runs the tool via a
handler continuation) and **vote / inverted-control** (the framework runs
the tool; the hook only votes allow/block). Per-framework research and
seam notes are in the cloud repo's `docs/integration/frameworks/`.

## Contributing an adapter

Every adapter must pass the **conformance suite**
(`kiff_guard.conformance`) — a contract that pins the invariants all
adapters share (observe is decide-independent and one-receipt; enforce is
one-receipt; unknown outcomes fail safe; the trust boundary holds). Add a
small `drive` shim in `tests/test_conformance.py` and pass it; that's the
bar, not a line-by-line audit.

**Support tiers:** a small set of adapters are maintained tier-1; the rest
are community/best-effort. Each adapter pins the framework version range
it's tested against, and CI runs against each framework's latest so
breakage shows as a red badge, not a silent rot.

## TypeScript SDK (planned)

`packages/js/` is reserved for `kiff-guard-js`. OpenClaw (a Node/TS
gateway) is the forcing function, and it unlocks the broader JS agent
ecosystem (LangGraph.js, Vercel AI SDK, Mastra). The decide-API contract
the SDKs speak is versioned and frozen (`/v1`, additive-only) so both
language SDKs target the same stable interface.

## License

MIT. See [LICENSE](./LICENSE).
