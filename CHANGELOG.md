# Changelog

All notable changes to the guard SDKs. This file covers both packages in
this repository — `kiff-guard` (PyPI) and `@kiff/kiff-guard` (npm) — which
share a version number and are released from the same tag.

## 1.3.0 — trusted run context

### Added

**Run context: the facts a harness asserts that the model cannot.** KIFF
Cloud's decide API gained a `run_context` field (kiff-cloud RFC 039). The
only proposal fields describing *why* an action is proposed —
`reasoning_summary`, `confidence` — are written by the model, so the
runtime had no independent account of the run. The guard is trusted
integrator code, which is where those facts belong.

```python
guard = Guard(client=c, mode="enforce",
              untrusted_tools={"read_public_issue", "fetch_url"})
```

```ts
const guard = new Guard({ client: c, mode: "enforce",
                          untrustedTools: ["read_public_issue", "fetch_url"] });
```

`untrusted_tools` / `untrustedTools` names the tools whose *results* bring
content from somewhere the agent's instructions do not: a fetched page, a
third-party ticket, a document. You declare the set up front; the guard
applies it mechanically by tool name. The model can choose to call such a
tool, and calling it can only ever *add* taint. `mark_untrusted_input()` /
`markUntrustedInput()` is the manual path for content that does not arrive
through a tool, and `start_run()` / `startRun()` begins a fresh run.

Four properties, the same in both SDKs:

- **Causal order.** The untrusted read itself is clean; everything after
  it is not. Taint applies after the tool runs.
- **One-way.** There is no `untaint()`; the property is read-only, and a
  test asserts those methods do not exist. The only reset is starting a
  new run, which the model has no route to.
- **Vote shape taints too**, on `record_executed` / `recordExecuted` — the
  only point where a guard whose adapter runs the tool itself learns that
  it ran.
- **Observe mode tracks it**, so flipping to enforce does not start from a
  false clean slate.

### Compatibility

Opt-in by construction. A guard that names no untrusted tools and sets no
run id sends no `run_context` and calls `Client.decide` with its original
signature, so every existing `Client` implementation — including custom
ones outside this repo — keeps working untouched.

Opting out is not a way to dodge the control: an action that declares a
run-context dependency and receives no assertion fails closed cloud-side.
Sending nothing means "I have not established anything", never "this run
is clean".

### Requires

KIFF Cloud with RFC 039 deployed. Against an older runtime the field is
ignored, since unknown JSON fields are dropped — an integrator would
believe they were governed while nothing read it. Upgrade the runtime
first.

### Honest limit

Run context is harness-*asserted*, not proven. A compromised integrator
can assert a clean run, exactly as one can decline to call the gate at
all. It defends against the model being manipulated, not against the
integrator being compromised.

## 1.2.0 — transport hardening and an honest approval receipt

### Security

**`allowed` is no longer accepted on a non-success status.** KIFF puts the
outcome in the response body by design and uses the HTTP status as a hint — it
returns 400 for `invalid`, 429 for `limit_exceeded` and 502 for infrastructure
failures, all of which are real governance answers the client must honour. It
never returns `allowed` on a non-2xx. The client now trusts the body for every
*withheld* outcome and additionally requires a success status for the one
outcome that lets a side effect run, so a proxy, captive portal or misdirected
`base_url` answering `500 {"outcome":"allowed"}` can no longer clear a call.

**A plaintext `base_url` is refused.** The API key rides every decide call, so
an `http://` endpoint puts a live credential on the wire and lets anyone on the
path rewrite the decision. Loopback (`localhost`, `127.0.0.1`, `::1`) is exempt
— it is the normal shape for local development and for this SDK's own test
doubles. For an out-of-band secure channel, opt in explicitly:

```python
HTTPClient(api_key=..., tool_map=..., allow_insecure_http=True)   # Python
```
```ts
new HTTPClient({ apiKey, toolMap, allowInsecureHttp: true })      // TypeScript
```

### Fixed

**The OpenClaw adapter recorded `executed: false` for approvals that executed.**
On `approval_required` it wrote a withheld receipt before returning
`requireApproval`. OpenClaw then pauses, routes to a human, and — if they
approve — runs the tool itself without calling back into the guard. The receipt
kept asserting the side effect had not happened. Money moved; the ledger said it
did not, on the very path the adapter exists to support.

`approval_required` now records through a new `recordPendingApproval`, which
leaves `executed` **unset** rather than false: the terminal outcome is genuinely
not observable at this seam, and absent is honest where false was wrong. The
blocked/invalid/limit_exceeded path still records `executed: false`, which is
accurate — the tool provably does not run. `Receipt.executed` is now optional;
**absent means unknown, never false.** TypeScript only.

All three were found by the same adversarial audit as 1.1.0.

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
