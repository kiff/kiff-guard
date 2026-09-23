/**
 * @kiff/kiff-guard — drop-in KIFF clearance for any agent's tool calls.
 *
 * The TypeScript SDK, a faithful port of the Python `kiff_guard` core.
 * Speaks the same versioned decide contract (RFC 017, /v1) and upholds
 * the same invariants (observe is decide-independent and one-receipt;
 * enforce is one governed receipt per call; unknown outcomes fail safe).
 *
 * Quickstart (zero-config audit, no KIFF account needed):
 *
 *     import { Guard } from "@kiff/kiff-guard";
 *     const guard = new Guard({ mode: "observe" });
 *     // attach guard via an adapter (e.g. OpenClaw), run the agent,
 *     // then read guard.receipts and exportYaml("my-domain", guard.catalog).
 *
 * Enforce (once you have a tenant + an active domain):
 *
 *     import { Guard, HTTPClient, ToolMap } from "@kiff/kiff-guard";
 *     const client = new HTTPClient({
 *       apiKey: "kiff_live_...",
 *       toolMap: new ToolMap().bind("refund_order", "REFUND_ORDER", "Order", "order_id"),
 *     });
 *     const guard = new Guard({ client, tenant: "...", agent: "support", mode: "enforce" });
 */

export { Catalog } from "./catalog.js";
export {
  ALLOWED,
  APPROVAL_REQUIRED,
  BLOCKED,
  INVALID,
  LIMIT_EXCEEDED,
  OBSERVED,
  WITHHELD,
  Decision,
  Hold,
  type Receipt,
} from "./decision.js";
export {
  type Client,
  type GuardConnectInput,
  type GuardConnection,
  type GuardConnector,
  type ToolBinding,
  type HTTPClientOptions,
  ToolMap,
  HTTPClient,
} from "./client.js";
export { Guard, type GuardConnectOptions, type GuardMode, type GuardOptions } from "./guard.js";
export { exportYaml } from "./draft.js";

// Sent to KIFF on every decide call as sdkVersion. Node has no reliable
// runtime read of package.json across ESM, CJS, and bundlers, so this stays
// a literal — and version.test.ts asserts it equals package.json, so the two
// cannot drift without turning CI red.
export const VERSION = "1.6.0";
