# Changelog

All notable changes to the guard SDKs. This file covers both packages in
this repository — `kiff-guard` (PyPI) and `@kiff/kiff-guard` (npm) — which
share a version number and are released from the same tag.

## 1.0.0 — first public release

The first release published to PyPI and npm. Everything below already
existed and was tested in this repository; 1.0.0 is the point at which it
becomes installable and the core API becomes a stability commitment.

### Python — `kiff-guard`

- `Guard`, `HTTPClient`, `ToolMap`, and the decision envelope: put a KIFF
  clearance check in front of a tool call. `observe` records; `enforce`
  refuses before the call runs.
- Zero required runtime dependencies. The core speaks the KIFF decide API
  over the standard library.
- Framework adapters, each an optional extra installing only its own host
  framework: Agno, LangGraph/LangChain, OpenAI Agents SDK, Google ADK,
  Pydantic AI, Strands, Microsoft Agent Framework, Hermes, Haystack, and
  LlamaIndex.
- A conformance suite adapters are checked against, so every seam produces
  the same decision behavior.
- `py.typed`: shipped type information.

### TypeScript — `@kiff/kiff-guard`

- The same core (`Guard`, `HTTPClient`, `ToolMap`) with bundled types.
- OpenClaw adapter at `@kiff/kiff-guard/adapters/openclaw`.

### Release engineering

- Tag-triggered release workflow publishing both packages from one tag,
  gated on the test suites and on the tag agreeing with both package
  versions.
- PyPI publishes via Trusted Publishing (OIDC, no stored token). npm
  publishes with `--provenance`, so the registry carries a verifiable link
  back to the commit and workflow that built the artifact.
- `LICENSE` is included in both distributions.

### Compatibility

Semantic versioning applies to the **core** API — `Guard`, `HTTPClient`,
`ToolMap`, and the decision shape. **Adapters track their upstream
framework** and may change within a minor release when a framework changes
its interception seam. See "Compatibility" in `README.md` for the reasoning.
