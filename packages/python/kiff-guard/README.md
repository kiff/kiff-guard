# kiff-guard

Drop-in KIFF clearance in front of any agent's tool calls. One guard,
two modes:

- **observe** — runs every tool, records an audit trail, and learns the
  action catalog. **No KIFF account, no domain, no API call required.**
  The fastest way to see what your agents actually do.
- **enforce** — asks KIFF to decide before each tool runs: `allowed`
  proceeds, `approval_required` / `blocked` / `invalid` hold the call.

The same one-line integration that governs your agent at runtime also
**derives a starter KIFF domain** from real traffic — so you never start
from a blank `kiff.yaml`.

## Install

```bash
pip install kiff-guard            # core, zero deps
pip install "kiff-guard[agno]"    # + the Agno adapter's framework
```

## Quickstart — audit your agent in under 5 minutes (zero config)

```python
from kiff_guard import Guard
from kiff_guard.adapters.agno import agno_hook

guard = Guard(mode="observe")     # no client, no tenant needed

agent = Agent(model=..., tools=[refund_order, send_email],
              tool_hooks=[agno_hook(guard)])

# ... run your agent as usual ...

for r in guard.receipts:
    print(r.state, r.tool, r.outcome)     # state == "observed"

from kiff_guard import export_yaml
print(export_yaml("my-domain", guard.catalog))   # your draft domain, free
```

Observe never calls KIFF and never blocks a tool. You get a real audit
trail of your own agent and a derived domain draft — the draft you then
review and activate before turning on enforcement.

With a Cloud credential you can push that derived draft straight to the
authoring UI instead of pasting it:

```python
guard = Guard(client=HTTPClient(api_key="kiff_live_...", tool_map=ToolMap()),
              tenant="<tenant>", agent="support", mode="observe")
# ... run your agent ...
result = guard.save_draft("my-domain")   # PUT /v1/me/domain/draft
print(result.valid, result.issues)       # the draft now shows up in Studio
```

`save_draft` renders the learned catalog with `export_yaml` and upserts it
to the cloud draft store. It's opt-in (separate from observe/enforce), so
zero-config audit stays local unless you explicitly call it.

## Enforce — once you have a tenant and an active domain

```python
from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.adapters.agno import agno_hook

client = HTTPClient(
    api_key="kiff_live_...",                  # mint in the dashboard
    tool_map=ToolMap().bind(
        "refund_order", action="REFUND_ORDER",
        entity_type="Order", entity_arg="order_id"),
)
guard = Guard(client=client, tenant="<tenant>", agent="support", mode="enforce")

agent = Agent(model=..., tools=[refund_order], tool_hooks=[agno_hook(guard)])
```

In enforce mode a withheld decision raises `kiff_guard.Hold`, carrying the
decision so your app can route it to a human (approval_required) or
surface the refusal. The API key's roles govern authority server-side —
the guard never asserts roles, so it cannot weaken the trust boundary.

## Custom agent? No adapter required

The adapters below are convenience glue for specific frameworks. They add
**no governance logic** — the guard logic lives in the core. If you run a
custom agent (your own loop, a framework with no adapter yet, Deno,
whatever), use the core directly. `HTTPClient` already speaks the hosted
decide route (`POST /v1/proposals/decide` against `api.kiff.dev`); there
is nothing extra to install or run.

**Observe — zero config, no KIFF account.** Call `observe` wherever your
loop is about to run a tool:

```python
from kiff_guard import Guard

guard = Guard(mode="observe")            # no client, no tenant

def run_tool(name, args):
    guard.observe(name, args)            # learn + record, never blocks
    return tools[name](**args)           # your agent runs the tool

# ... after the run:
for r in guard.receipts:
    print(r.state, r.tool, r.outcome)    # state == "observed"
```

**Enforce — decide before you run.** Gate on `decision.withheld` (true for
anything that isn't an explicit `allowed`, so an unknown future outcome
fails safe), then record exactly one receipt:

```python
from kiff_guard import Guard, HTTPClient, ToolMap

client = HTTPClient(
    api_key="kiff_live_...",
    tool_map=ToolMap().bind(
        "refund_order", action="REFUND_ORDER",
        entity_type="Order", entity_arg="order_id"),
)
guard = Guard(client=client, tenant="<tenant>", agent="support", mode="enforce")

def run_tool(name, args):
    decision = guard.decide_only(name, args)     # calls KIFF, does not run
    if decision.withheld:                         # != "allowed" → withhold
        guard.record_withheld(name, args, decision)
        return f"withheld: {decision.outcome} — {decision.reason}"
    result = tools[name](**args)                  # your agent runs the tool
    guard.record_executed(name, args, decision)   # one receipt per call
    return result
```

This is the same core the adapters call; an adapter just translates one
framework's pre-tool seam into these calls. You send `actor_id` (the
`agent`); you never send roles — the API key's roles govern authority
server-side, so your only integration responsibility is authenticating the
caller's identity, not granting it.

For stacks the SDKs don't cover (Ruby, Go, shell), a proposal is a single
HTTP POST — see
[`cookbook/custom-agent-http`](../../../cookbook/custom-agent-http/).

## Architecture

A **framework-agnostic core** (`Guard.evaluate`) plus **thin adapters**,
one per framework, each translating that framework's pre-tool-execution
seam into a single `evaluate` call. The guard logic lives in the core,
once; an adapter adds no governance logic of its own.

| Framework | Adapter | Status |
|---|---|---|
| Agno | `kiff_guard.adapters.agno` | shipped |
| Hermes (Nous) | `kiff_guard.adapters.hermes` | shipped |
| LangGraph / LangChain | `kiff_guard.adapters.langgraph` | shipped |
| OpenAI Agents SDK | `kiff_guard.adapters.openai_agents` | shipped |
| Google ADK | `kiff_guard.adapters.google_adk` | shipped |
| Pydantic AI | `kiff_guard.adapters.pydantic_ai` | shipped |
| Strands Agents | `kiff_guard.adapters.strands` | shipped |
| Haystack Agents | `kiff_guard.adapters.haystack` | shipped |
| Microsoft Agent Framework | `kiff_guard.adapters.microsoft_agent_framework` | shipped |
| LlamaIndex | `kiff_guard.adapters.llama_index` | shipped |
| OpenClaw (TypeScript) | `@kiffhq/kiff-guard/adapters/openclaw` (`packages/js`) | shipped |

Each adapter documents its verified pre-tool-execution seam and block
contract in its module docstring. See the two adapter shapes below.

### Two adapter shapes

- **Middleware** (Agno, LangGraph / LangChain, …): the guard runs the
  tool via `Guard.evaluate(tool, args, run=...)`.
- **Inverted-control** (Hermes, OpenAI Agents SDK, …): the framework runs
  the tool; the hook only votes. Adapters use `Guard.observe()` /
  `Guard.decide_only()` and act on the returned `Decision` — no run
  callback.

#### Hermes (Nous Research)

Ship a Hermes plugin (`~/.hermes/plugins/kiff-guard/`) whose
`__init__.py` wires the guard into Hermes' `pre_tool_call` hook:

```python
from kiff_guard import Guard
from kiff_guard.adapters.hermes import register_kiff_guard

_GUARD = Guard(mode="observe")        # zero-config audit; no KIFF account

def register(ctx):
    register_kiff_guard(ctx, _GUARD)
```

In observe mode the hook records + learns every tool call and never
blocks. In enforce mode (`Guard(client=..., mode="enforce")`) a withheld
KIFF decision returns Hermes' `{"action": "block", ...}` directive so the
tool never runs. Enforce fails closed on a guard error by default (a
control tower shouldn't wave traffic through when its decision path is
down); pass `fail_closed=False` to override.

#### OpenAI Agents SDK

Attach the guard as a **tool input guardrail** on a `function_tool`:

```python
from agents import Agent, function_tool
from kiff_guard import Guard
from kiff_guard.adapters.openai_agents import kiff_tool_input_guardrail

guard = Guard(mode="observe")     # zero-config audit; no KIFF account
kiff_gd = kiff_tool_input_guardrail(guard)

@function_tool(tool_input_guardrails=[kiff_gd])
def refund_order(order_id: str, amount_cents: int) -> str:
    ...

agent = Agent(name="support", tools=[refund_order])
```

The tool input guardrail runs **before** the tool executes (verified
against openai-agents v0.17.4). In observe mode it records + learns and
always allows. In enforce mode (`Guard(client=..., mode="enforce")`) a
withheld KIFF decision returns `ToolGuardrailFunctionOutput.reject_content(reason)`
so the SDK skips the tool and hands the reason to the model — without
running it. Enforce fails closed on a guard error by default. Install the
SDK with `pip install "kiff-guard[openai]"` (the `openai` extra maps to
the `openai-agents` package).

> The tool input guardrail — not `needs_approval` — is the synchronous
> policy seam. `needs_approval` is the heavyweight human-pause path (the
> run pauses and surfaces `interruptions`, resumed via RunState); KIFF's
> gate is a machine decision that belongs in the guardrail.

### LangGraph / LangChain

Wrap the guard as `wrap_tool_call` middleware on a LangChain agent:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from kiff_guard import Guard
from kiff_guard.adapters.langgraph import kiff_wrap_tool_call

guard = Guard(mode="observe")     # zero-config audit; no KIFF account
kiff_mw = wrap_tool_call(kiff_wrap_tool_call(guard))

agent = create_agent(model="...", tools=[...], middleware=[kiff_mw])
```

In observe mode the middleware runs each tool via the handler, records +
learns, and never blocks. In enforce mode (`Guard(client=..., mode=
"enforce")`) a withheld KIFF decision returns a `ToolMessage`
(`status="error"`) carrying the reason **without** running the tool — the
same short-circuit pattern LangChain's built-in `ShellAllowListMiddleware`
uses. Install the framework with `pip install "kiff-guard[langgraph]"`.

#### LlamaIndex

Subclass `AgentWorkflow` via `GuardedAgentWorkflow`, which overrides the
`call_tool` step to insert the KIFF gate before `_call_tool` runs:

```python
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai import OpenAI
from kiff_guard import Guard
from kiff_guard.adapters.llama_index import GuardedAgentWorkflow

guard = Guard(mode="observe")     # zero-config audit; no KIFF account

workflow = GuardedAgentWorkflow(
    agents=[FunctionAgent(tools=[...], llm=OpenAI(model="gpt-4o-mini"))],
    guard=guard,
)
result = await workflow.run(user_msg="...")
```

The seam is `AgentWorkflow.call_tool` — a `@step` that receives a
`ToolCall` event (`tool_name`, `tool_kwargs`, `tool_id`) before the tool
body runs. This is a **middleware shape**: the guard closure over
`_call_tool` is the continuation. In enforce mode a withheld decision
raises `Hold` so the tool never runs. Install with
`pip install "kiff-guard[llama-index]"`.

## Conformance & verification

Every adapter must pass the **conformance suite** (`kiff_guard.conformance`)
— a `storetest`-style contract that pins the invariants all adapters
share, both shapes:

- observe never calls the client, always runs the tool, records exactly
  one `observed` receipt, learns the catalog, and works with no client/
  tenant;
- enforce allowed → tool runs + exactly one governed `executed=True`
  receipt; enforce withheld → tool does not run + exactly one governed
  `executed=False` receipt (the one-receipt rule);
- the guard never injects a `roles` field (trust boundary).

A new adapter is "done" when it has a `drive` shim in
`tests/test_conformance.py` and passes. This is the durability mechanism:
a community adapter can be accepted by passing conformance rather than a
line-by-line audit, and CI catches upstream framework drift.

```bash
python -m pytest tests/           # full offline suite incl. conformance
```

`live_openai_check.py` verifies the OpenAI Agents adapter against the
**real** `openai-agents` SDK + a live model call (the SDK accepts the
guardrail, `reject_content` genuinely skips the tool, one receipt per
call). It needs a 3.10+ env, `pip install openai-agents`, and
`OPENAI_API_KEY` in the environment; it is operator-run, not part of CI.

## License

MIT.