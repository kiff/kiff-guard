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
