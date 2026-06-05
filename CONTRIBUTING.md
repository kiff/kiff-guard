# Contributing to kiff-guard

Thanks for your interest. The most valuable contribution is a new adapter — one
that passes the conformance suite and adds CI coverage against the framework's
latest. Read this before opening a PR.

## What lives here

kiff-guard is the **client SDK + framework adapters** for KIFF. It is not the
KIFF framework (`kiffhq/kiff`) and not KIFF Cloud. It is a thin,
framework-agnostic core plus one adapter per agent framework. Governance logic
lives in the core once; adapters add none of their own.

## Two adapter shapes

Pick by how the framework hands you control:

- **middleware** (`agno tool_hooks`, `LangGraph wrap_tool_call`): the guard runs
  the tool via the `run=` continuation → use `Guard.evaluate`.
- **vote / inverted-control** (`Hermes pre_tool_call`, OpenAI tool-input
  guardrail, Google ADK `before_tool_callback`, Pydantic AI
  `before_tool_execute`): the framework runs the tool; the hook only votes →
  use `Guard.observe` / `Guard.decide_only` + `Guard.record_executed` /
  `Guard.record_withheld`.

Never call `evaluate(run=...)` from a vote adapter.

## Non-negotiable invariants

Every adapter must preserve these — the conformance suite enforces them:

1. **One receipt per call.** `decide_only` does not record; vote adapters record
   exactly once (`record_executed` on allowed, `record_withheld` on withheld).
2. **Fail-safe on unknown outcomes.** Gate on `decision.withheld` (defined as
   `outcome != "allowed"`), never on membership in a known outcome set.
3. **Fail-closed in enforce by default.** A guard/transport error blocks the
   tool. `fail_closed=False` is opt-in.
4. **Trust boundary.** The adapter never injects a `roles` or authority field.
   Authority is the API key's, enforced server-side.
5. **Lazy host-framework import.** The adapter imports its framework only inside
   the factory/callable — never at module level. `import kiff_guard` must work
   with no framework installed.

## How to add an adapter

1. **Source-verify the seam.** Confirm the framework's pre-tool-execution hook
   signature and block contract against current upstream docs/source. Record
   what you verified in the module docstring.

2. **Create `src/kiff_guard/adapters/<framework>.py`** with:
   - A module docstring stating: the seam, the verified block contract, and the
     shape (middleware or vote).
   - A single factory returning the framework-shaped callable.
   - No framework imports at module level (lazy only).

3. **Add an optional extra in `pyproject.toml`**:
   ```toml
   [project.optional-dependencies]
   my-framework = ["my-framework-package"]
   ```

4. **Add a conformance driver in `tests/test_conformance.py`**:
   - A `_drive_<framework>` shim that exercises the guard primitives through
     your adapter.
   - A `test_<framework>_conformance` test that calls `run_conformance` with
     your driver.
   - The shim must degrade cleanly when the host framework is not installed,
     exercising the guard primitives directly.

5. **Add a dedicated `tests/test_<framework>_adapter.py`** covering: observe,
   enforce-allowed, enforce-withheld, fail-closed, fail-open, unknown-outcome.
   Use a stub client; tests must run without the host framework installed.

6. **Add a CI job in `.github/workflows/python.yml`** mirroring `adapter-agno`:
   ```yaml
   adapter-<framework>:
     name: adapter (<framework> @ latest)
     runs-on: ubuntu-latest
     continue-on-error: true
     defaults:
       run:
         working-directory: packages/python/kiff-guard
     steps:
       - uses: actions/checkout@v4
       - uses: actions/setup-python@v5
         with:
           python-version: "3.12"
       - run: pip install -e ".[dev,<framework>]"
       - run: python -m pytest tests/ -q -k "<framework> or conformance or guard_core"
   ```

7. **Run the full offline suite** before opening a PR:
   ```bash
   python -m pytest tests/ -q
   ```
   All 73+ tests must pass (no framework installed required for the core suite).

## An adapter is "done" when

- [ ] Seam source-verified and documented in the module docstring
- [ ] Conformance suite passes: `run_conformance` driver added, O1–O5 + E1–E4 green
- [ ] Dedicated adapter test file added (`tests/test_<framework>_adapter.py`)
- [ ] CI job added in `python.yml`
- [ ] Optional extra added in `pyproject.toml`
- [ ] Lazy-import invariant verified: `import kiff_guard` works with no framework installed

## Running the tests

```bash
cd packages/python/kiff-guard
python -m pytest tests/ -q                        # full offline suite (no framework needed)
python -m pytest tests/ -q -k "conformance"       # conformance suite only
python -m pytest tests/ -q -k "guard_core"        # core invariants only
```

With a specific framework installed:
```bash
pip install -e ".[dev,agno]"
python -m pytest tests/ -q -k "agno or conformance or guard_core"
```

## Code style

- Python ≥ 3.9. The offline core is stdlib-only; zero required runtime deps.
- Match the existing adapter style (module docstring, single factory).
- Type the `guard` parameter as `Guard` in new adapters.
- `gofmt` / `go vet` for any Go changes in cookbook recipes.
- No new runtime dependencies in the core (`src/kiff_guard/` excluding adapters).

## Cookbook recipes

Recipes live in `cookbook/`. They are complete runnable proofs, not tutorials.
Each recipe needs: `README.md`, `PROOF.md`, `MANIFEST.md`, `.env.example`,
`requirements.txt`, a `kiff-decide/` Go gate, an `app/` system of record, an
`agent/` using an existing adapter, and a `driver/scenario.py`. No new
governance logic in recipes — they use the core primitives.

## Questions

Open a GitHub Discussion or an issue. For security issues see [SECURITY.md](./SECURITY.md).
