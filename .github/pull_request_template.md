## Summary

<!-- What does this PR do and why? -->

## Type of change

- [ ] New adapter
- [ ] Core SDK change (`guard.py`, `client.py`, `decision.py`, `conformance.py`)
- [ ] Cookbook recipe
- [ ] Docs / README
- [ ] CI / tooling
- [ ] Bug fix

---

## Adapter checklist (required for new adapters, skip otherwise)

- [ ] **Seam source-verified** — confirmed the framework's pre-tool hook signature and block contract against current upstream docs/source; recorded in the module docstring with the verified commit/date
- [ ] **Shape declared** — middleware (`evaluate`) or vote (`decide_only` + `record_executed`/`record_withheld`); never `evaluate` from a vote adapter
- [ ] **One receipt per call** — `decide_only` does not record; vote adapters call `record_executed` XOR `record_withheld` exactly once
- [ ] **Fail-safe on unknown outcomes** — gates on `decision.withheld`, not membership in a known outcome set
- [ ] **Trust boundary** — adapter never injects `roles` or any authority field
- [ ] **Lazy import** — no framework import at module level; `import kiff_guard` works with no framework installed
- [ ] **Conformance driver** added in `tests/test_conformance.py`; `run_conformance` passes (O1–O5 + E1–E4)
- [ ] **Dedicated adapter test file** added (`tests/test_<framework>_adapter.py`): observe / enforce-allowed / enforce-withheld / fail-closed / fail-open / unknown-outcome
- [ ] **CI job** added in `.github/workflows/python.yml` mirroring `adapter-agno`
- [ ] **Optional extra** added in `pyproject.toml`
- [ ] **Full offline suite** passes locally: `python -m pytest tests/ -q`

## Core SDK checklist (required for core changes, skip otherwise)

- [ ] No new required runtime dependencies introduced
- [ ] Lazy-import invariant preserved: `import kiff_guard` works with no framework installed
- [ ] Trust boundary preserved: no `roles`/authority injected
- [ ] Fail-safe preserved: unknown outcomes block in enforce mode

## Verification

<!-- What did you run? Paste counts, not just "tests pass". -->

```
python -m pytest tests/ -q
# X passed
```
