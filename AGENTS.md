# AGENTS.md — kiff-guard

Protocol for agents working in this repo. Read this before making changes
or reviewing PRs.

## What this repo is

kiff-guard is the **client SDK + framework adapters** for KIFF — drop-in
KIFF clearance in front of any agent's tool calls. MIT-licensed,
community-maintainable.

- It is **not** the KIFF framework (that's `kiffhq/kiff`, Go).
- It is **not** the hosted runtime (that's KIFF Cloud).
- It is a thin, framework-agnostic **core** plus one **adapter** per agent
  framework. The guard logic lives in the core, once; an adapter adds no
  governance logic of its own.

One guard, two modes:

- **observe** — runs every tool, records an audit trail, learns the action
  catalog. Decide-independent: no client, no tenant, no KIFF account, no
  API call. Never blocks.
- **enforce** — asks KIFF to decide before each tool runs. `allowed`
  proceeds; anything else (including unknown future outcomes) withholds.
  Fail-safe by construction.

## Repository layout

```
packages/
  python/kiff-guard/        # the Python SDK (shipped)
    src/kiff_guard/
      guard.py              # the framework-agnostic core (Guard)
      decision.py           # value types: Decision, Receipt, Hold + outcomes
      catalog.py            # learned action catalog
      client.py             # KIFF HTTP client (stdlib urllib), ToolMap
      conformance.py        # the contract every adapter must pass
      draft.py              # derive a starter domain YAML from the catalog
      adapters/             # one thin adapter per framework
    tests/                  # offline suite incl. conformance drivers
    pyproject.toml          # extras: one per adapter framework
  js/                       # the TypeScript SDK (planned, kiff-guard-js)
```

Core logic belongs in `src/kiff_guard/`. Framework-specific glue belongs
only in `src/kiff_guard/adapters/`. Do not push framework imports into the
core — `import kiff_guard` must work with no framework installed.

## Architecture rules

The core exposes the only primitives adapters may build on:

- `Guard.observe(tool, args)` — learn + record one `observed` receipt. No
  decision, no run. (observe mode)
- `Guard.decide_only(tool, args)` — learn + call KIFF, return the
  `Decision`. Does NOT run the tool and does NOT record. (enforce, vote
  shape)
- `Guard.record_executed` / `Guard.record_withheld` — the vote-shape
  adapter's single audit write. One receipt per call.
- `Guard.evaluate(tool, args, run=...)` — convenience for middleware
  frameworks that let the guard run the tool itself.

Two adapter shapes, pick by how the framework hands you control:

- **middleware** (Agno `tool_hooks`, LangGraph `wrap_tool_call`): the
  guard runs the tool via the `run=` continuation → use `evaluate`.
- **vote / inverted-control** (Hermes `pre_tool_call`, OpenAI tool input
  guardrail, Google ADK `before_tool_callback`, Pydantic AI
  `before_tool_execute`): the framework runs the tool; the hook only
  votes → use `observe` / `decide_only` + `record_executed` /
  `record_withheld`. Never call `evaluate(run=...)` from a vote adapter.

Non-negotiable invariants:

1. **One receipt per call.** Deciding and recording are separate; the
   adapter records exactly once (allowed → executed=True, withheld →
   executed=False).
2. **Fail-safe on unknown outcomes.** Gate on `decision.withheld`
   (defined as `outcome != "allowed"`), never on membership in a known
   set. A new cloud outcome must block, not slip through.
3. **Fail-closed in enforce by default.** A guard/transport error blocks
   the tool. `observe` always fails open (it never blocks anyway).
   `fail_closed=False` is opt-in and discouraged.
4. **Trust boundary.** The guard never injects a `roles`/authority field.
   Authority is the API key's, enforced server-side.
5. **Lazy host-framework import.** Adapters import their framework lazily
   (inside the factory or when building a real result), so `import
   kiff_guard` never requires any framework. The framework comes from the
   adapter's optional extra (`pip install "kiff-guard[<name>]"`).
6. **Source-verify the seam.** Before writing an adapter, confirm the
   framework's pre-tool-execution hook signature and block contract
   against current upstream docs/source. Record what you verified in the
   module docstring.

## Coding rules

- Python ≥ 3.9 floor (the offline core is stdlib-only; zero required
  runtime deps).
- Match the existing adapter style: a module docstring stating the seam,
  the verified block contract, and the shape; a single factory returning
  the framework-shaped callable.
- Type the `guard` parameter as `Guard` where practical (new adapters
  should; some older ones use `Any`).
- Keep errors explicit. observe swallows audit/learn errors (it must
  never block); enforce surfaces them per the fail-closed rule.
- Add an optional extra in `pyproject.toml` for each new adapter
  framework.

## Testing protocol

- Run the full offline suite before finishing any change:
  ```bash
  python -m pytest tests/ -q
  ```
- **Every adapter must pass the conformance suite**
  (`kiff_guard.conformance`). A new adapter is "done" only when it has a
  `drive` shim in `tests/test_conformance.py` and passes O1–O5 + E1–E4.
  Conformance is the durability mechanism: an adapter is accepted by
  passing it, not by a line-by-line audit.
- Add a dedicated `tests/test_<framework>_adapter.py` covering observe /
  enforce-allowed / enforce-withheld / fail-closed / fail-open /
  unknown-outcome. Use a stub client and an injectable skip/exception so
  tests run without the host framework installed.
- Add a per-adapter CI job in `.github/workflows/python.yml` mirroring the
  `adapter-agno` job: `continue-on-error: true` (best-effort tier),
  installing `".[dev,<extra>]"` and running
  `-k "<framework> or conformance or guard_core"`. CI runs each adapter
  against its framework's **latest** so upstream drift shows as a red
  badge → a PR, not silent rot.

## PR review protocol

When asked to **review a PR**, "review" means validate AND record the
verdict on GitHub — not just describe it in chat.

1. `gh pr view <n>` and `gh pr diff <n>` to read the change and its claims.
2. `gh pr checkout <n>`, then actually run it:
   - `python -m pytest tests/ -q` (confirm the claimed counts).
   - Verify lazy-import claims (`import kiff_guard` + the new adapter with
     no host framework installed).
   - Spot-check any framework-contract claims against current upstream
     docs/source.
   - Confirm conformance: the new adapter has a driver and the suite
     passes.
3. Restore the working tree (`git checkout main`) when done.
4. **Submit the review on GitHub** with the validation summary:
   - `gh pr review <n> --approve --body "..."` when it passes, or
   - `gh pr review <n> --request-changes --body "..."` with specifics, or
   - `gh pr review <n> --comment --body "..."` for non-blocking notes.
   Do not stop at a chat-only assessment when a review was requested.

Note: GitHub rejects self-approval. Check `gh api user --jq .login`
against the PR author; if they match, fall back to `--comment`.

## Git safety

- Never push to `main`/`master` directly. Push to a branch.
- Only create commits when explicitly asked.
- No destructive git (`reset --hard`, force-push, `clean -f`, `branch -D`)
  without explicit permission.
- Flag any file that may carry secrets before committing.

## Current goal

Grow the verified Python adapter set (each gated on source-verification +
conformance), keep the core thin and dependency-free, and keep the audit
trail honest (observe = real record, not a governance verdict). The
TypeScript SDK (`packages/js/`, `kiff-guard-js`) is the next language
target; OpenClaw is its forcing function and is intentionally not a Python
adapter.
