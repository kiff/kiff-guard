# @kiffhq/kiff-guard (TypeScript)

Drop-in KIFF clearance for any agent's tool calls — **observe** to audit,
**enforce** to govern. The TypeScript SDK, a faithful port of the Python
[`kiff-guard`](../python/kiff-guard) core.

It speaks the same versioned decide contract (`POST /v1/proposals/decide`,
RFC 017, additive-only `/v1`) and upholds the same invariants the Python
SDK does, pinned by the conformance suite:

- **observe is decide-independent** — works with no client and no tenant;
- **one governed receipt per tool call**;
- **unknown outcomes fail safe** — anything that isn't an explicit
  `allowed` withholds, so the cloud can add outcomes without old SDKs
  failing open;
- **roles are never sent** — the API key's roles govern server-side.

Zero required runtime dependencies (uses the global `fetch`, Node >= 18).

## Quickstart (zero-config audit, no KIFF account)

```ts
import { Guard, exportYaml } from "@kiffhq/kiff-guard";
import { registerKiffGuard } from "@kiffhq/kiff-guard/adapters/openclaw";

const guard = new Guard({ mode: "observe" });
// attach via the OpenClaw plugin (below); run the agent; then:
for (const r of guard.receipts) console.log(r.state, r.tool, r.outcome);
console.log(exportYaml("my-domain", guard.catalog));
```

## Enforce (with a tenant + active domain)

```ts
import { Guard, HTTPClient, ToolMap } from "@kiffhq/kiff-guard";

const client = new HTTPClient({
  apiKey: "kiff_live_...",                       // mint in the dashboard
  toolMap: new ToolMap().bind("refund_order", "REFUND_ORDER", "Order", "order_id"),
});
const guard = new Guard({ client, tenant: "<tenant>", agent: "support", mode: "enforce" });
```

## Custom agent? No adapter required

The adapter below is convenience glue for OpenClaw. It adds **no
governance logic** — the guard logic lives in the core. If you run a
custom agent (your own loop, a Deno/Node service, a framework with no
adapter yet), use the core directly. `HTTPClient` already speaks the
hosted decide route (`POST /v1/proposals/decide` against `api.kiff.dev`);
there is nothing extra to install or run.

**Observe — zero config, no KIFF account.** Call `observe` wherever your
loop is about to run a tool:

```ts
import { Guard } from "@kiffhq/kiff-guard";

const guard = new Guard({ mode: "observe" });   // no client, no tenant

function runTool(name: string, args: Record<string, unknown>) {
  guard.observe(name, args);                    // learn + record, never blocks
  return tools[name](args);                     // your agent runs the tool
}
// ... after the run: guard.receipts each have state === "observed".
```

**Enforce — decide before you run.** Gate on `decision.withheld` (true for
anything that isn't an explicit `allowed`, so an unknown future outcome
fails safe), then record exactly one receipt:

```ts
import { Guard, HTTPClient, ToolMap } from "@kiffhq/kiff-guard";

const client = new HTTPClient({
  apiKey: "kiff_live_...",
  toolMap: new ToolMap().bind("refund_order", "REFUND_ORDER", "Order", "order_id"),
});
const guard = new Guard({ client, tenant: "<tenant>", agent: "support", mode: "enforce" });

async function runTool(name: string, args: Record<string, unknown>) {
  const decision = await guard.decideOnly(name, args);   // calls KIFF, does not run
  if (decision.withheld) {                                // != "allowed" → withhold
    guard.recordWithheld(name, args, decision);
    return `withheld: ${decision.outcome} — ${decision.reason}`;
  }
  const result = tools[name](args);                       // your agent runs the tool
  guard.recordExecuted(name, args, decision);             // one receipt per call
  return result;
}
```

This is the same core the OpenClaw adapter calls; an adapter just
translates one framework's pre-tool seam into these calls. You send
`actorId` (the `agent`); you never send roles — the API key's roles govern
authority server-side, so your only integration responsibility is
authenticating the caller's identity, not granting it.

For stacks neither SDK covers (Ruby, Go, shell), a proposal is a single
HTTP POST — see
[`cookbook/custom-agent-http`](../../cookbook/custom-agent-http/).

## Connect to KIFF Cloud

Call `connect` when you want the hosted dashboard to show a live guard
runtime. Run it at startup and periodically as a heartbeat. It is explicit so
local `observe` mode stays zero-config and never phones home unless you provide
a Cloud client.

```ts
await guard.connect({
  adapter: "openclaw",
  project: "finance",
  environment: "prod",
  workflow: "duplicate-payment",
  sdkVersion: "0.1.0",
});
```

Cloud stores the tenant from the API key plus the project, environment, agent,
workflow, adapter, SDK version, mode, first/last seen time, and heartbeat count.

## Adapters

| Framework | Lang | Shape | Status |
|---|---|---|---|
| OpenClaw | ts | vote (`before_tool_call`) | shipped |

OpenClaw is the first adapter where KIFF's `approval_required` renders as
**native human-in-the-loop** (`requireApproval` → the `/approve` flow),
not a collapse to a block. More JS-ecosystem adapters (LangGraph.js,
Vercel AI SDK, Mastra) follow.

### OpenClaw plugin

```ts
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { Guard } from "@kiffhq/kiff-guard";
import { registerKiffGuard } from "@kiffhq/kiff-guard/adapters/openclaw";

const guard = new Guard({ mode: "observe" }); // or enforce with a client

export default definePluginEntry({
  id: "kiff-guard",
  name: "KIFF Guard",
  register(api) {
    registerKiffGuard(api, guard);
  },
});
```

`observe` records + learns every tool call and never blocks. `enforce`
calls KIFF before each tool: `allowed` proceeds, `approval_required`
routes a real human via `requireApproval`, everything else (and any
unknown outcome) blocks. Fail-closed by default if the decide path is
down.

## Develop

```bash
npm install
npm run typecheck   # tsc strict, no emit
npm run build       # -> dist/
npm test            # vitest: guard core + conformance + adapter
```

The conformance suite (`src/conformance.test.ts`) is the durability
contract: a new adapter provides a `drive` shim and the shared
invariants (O1–O5 observe, E1–E4 enforce, incl. fail-safe-on-unknown) do
the rest. Same posture as the Python SDK's `conformance.py`.
