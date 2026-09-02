# Changelog

All notable changes to the guard SDKs. This file covers both packages in
this repository — `kiff-guard` (PyPI) and `@kiff/kiff-guard` (npm) — which
share a version number and are released from the same tag.

## 1.1.0 — unbound tools no longer clear themselves

### Security

**An unbound tool was cleared without asking KIFF.** `HTTPClient.decide`
returned `allowed` for any tool missing from the `ToolMap`, with the reason
`"<tool> unmapped; cleared and audited"` — for a call the runtime never saw.
No HTTP request left the process, the tool ran, and the receipt recorded the
call as governed and allowed.

This affected **both SDKs at 1.0.0** (`kiff-guard` on PyPI, `@kiff/kiff-guard`
on npm) in `enforce` mode. The practical failure is a binding you forgot: an
agent gains a tool, nobody adds it to the `ToolMap`, and that tool is ungoverned
while the evidence stream says otherwise. A governance SDK that emits a false
clearance is worse than no SDK, because the receipt is what people trust later.

Found by an adversarial audit of this repository. The reproduction pointed a
built wheel at a loopback KIFF scripted to answer `blocked` to everything, then
called an unbound `wire_transfer`: the tool executed, `0` HTTP calls were made,
and the receipt read `state='governed' outcome='allowed' executed=True`.

**Fixed.** An unbound tool now returns `invalid`, which is a withheld outcome,
so `enforce` refuses and the adapters' existing fail-closed paths apply. The
reason names the tool and how to fix it.

### Breaking

`HTTPClient` now defaults to `unmapped="withhold"`. If you relied on unbound
tools being cleared — a staged rollout with a partially-filled `ToolMap` — you
will now see `invalid` decisions instead of silent passes. That is the bug being
fixed, but the previous behavior remains available explicitly:

```python
HTTPClient(api_key=..., tool_map=..., unmapped="allow")   # Python
```
```ts
new HTTPClient({ apiKey, toolMap, unmapped: "allow" })    // TypeScript
```

Passing anything other than `"withhold"` or `"allow"` raises. Prefer binding the
tool: an `unmapped="allow"` deployment governs only what you remembered to map.

### Fixed

- `SECURITY.md` claimed 0.1.x was the supported line, four releases out of date.

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
