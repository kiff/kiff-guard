// kiff-guard-demo — an OpenClaw plugin that registers a `pay_invoice`
// tool AND gates every tool call through KIFF via the kiff-guard-js
// before_tool_call adapter.
//
// This is the integration centerpiece of the duplicate-payment-guard
// recipe. Two surfaces in one plugin (so we use definePluginEntry, not
// defineToolPlugin):
//
//   1. a `pay_invoice` tool that calls the ap-app /pay endpoint (the
//      real side effect — the debit).
//   2. a `before_tool_call` hook (from @kiffhq/kiff-guard/adapters/openclaw)
//      in ENFORCE mode, pointed at the KIFF decide server. Before any
//      tool runs, KIFF decides. PAY_INVOICE on a PENDING invoice ->
//      allowed; the retry on a now-PAID invoice -> blocked, and the tool
//      never executes.
//
// Config (from plugins.entries["kiff-guard-demo"].config):
//   kiffBaseUrl  - the KIFF decide server (http://kiff-decide:8081)
//   apAppUrl     - the ap-app system of record (http://ap-app:8082)
//
// Optional Cloud discovery:
//   KIFF_CLOUD_API_KEY      - dashboard API key for runtime registration
//   KIFF_CLOUD_API_URL      - cloud API, defaults to https://api.kiff.dev
//   KIFF_CLOUD_PROJECT      - project grouping, defaults to cookbook
//   KIFF_CLOUD_ENVIRONMENT  - environment grouping, defaults to local
//   KIFF_CLOUD_WORKFLOW     - workflow grouping, defaults to duplicate-payment

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { Guard, HTTPClient, ToolMap, VERSION } from "@kiffhq/kiff-guard";
import { kiffBeforeToolCall } from "@kiffhq/kiff-guard/adapters/openclaw";

const KIFF_BASE = process.env.KIFF_BASE_URL || "http://kiff-decide:8081";
const AP_APP = process.env.AP_APP_URL || "http://ap-app:8082";
const KIFF_CLOUD_API_KEY = process.env.KIFF_CLOUD_API_KEY || "";
const KIFF_CLOUD_API_URL = process.env.KIFF_CLOUD_API_URL || "https://api.kiff.dev";
const KIFF_CLOUD_PROJECT = process.env.KIFF_CLOUD_PROJECT || "cookbook";
const KIFF_CLOUD_ENVIRONMENT = process.env.KIFF_CLOUD_ENVIRONMENT || "local";
const KIFF_CLOUD_WORKFLOW = process.env.KIFF_CLOUD_WORKFLOW || "duplicate-payment";

// Bind the agent's `pay_invoice` tool to the PAY_INVOICE action contract.
// entityArg names the tool argument that carries the entity id — the
// guard reads args.invoice_id as the KIFF entity_id and excludes it from
// the parameters it forwards.
const toolMap = new ToolMap().bind("pay_invoice", "PAY_INVOICE", "Invoice", "invoice_id");

const client = new HTTPClient({
  apiKey: "kiff_live_demo_local", // the standalone decide server ignores auth
  toolMap,
  baseUrl: KIFF_BASE,
});

// Enforce mode: KIFF decides before each tool call; a withheld decision
// blocks the tool. fail-closed by default.
const guard = new Guard({ client, tenant: "demo", agent: "ap-agent", mode: "enforce" });

const cloudClient = KIFF_CLOUD_API_KEY
  ? new HTTPClient({
      apiKey: KIFF_CLOUD_API_KEY,
      toolMap,
      baseUrl: KIFF_CLOUD_API_URL,
    })
  : undefined;
const cloudGuard = cloudClient
  ? new Guard({
      client: cloudClient,
      tenant: "cloud",
      agent: "ap-agent",
      mode: "enforce",
    })
  : undefined;
let warnedCloudRegistration = false;

function refreshCloudConnection(): void {
  if (!cloudGuard || !cloudClient) return;
  void cloudGuard
    .connect({
      adapter: "openclaw",
      project: KIFF_CLOUD_PROJECT,
      environment: KIFF_CLOUD_ENVIRONMENT,
      workflow: KIFF_CLOUD_WORKFLOW,
      sdkVersion: VERSION,
    })
    .then(() =>
      cloudClient.observeGuard({
        agentId: "ap-agent",
        adapter: "openclaw",
        mode: "enforce",
        project: KIFF_CLOUD_PROJECT,
        environment: KIFF_CLOUD_ENVIRONMENT,
        workflow: KIFF_CLOUD_WORKFLOW,
        sdkVersion: VERSION,
        tools: [
          {
            name: "pay_invoice",
            description:
              "Pay an outstanding invoice by id. Debits the account and marks the invoice paid.",
            entityArg: "invoice_id",
            action: "PAY_INVOICE",
            entityType: "Invoice",
            required: ["amount_cents"],
            parameterSchema: {
              type: "object",
              additionalProperties: false,
              properties: {
                invoice_id: {
                  type: "string",
                  description: "The invoice id to pay, e.g. inv-001.",
                },
                amount_cents: { type: "integer", description: "Amount in cents." },
              },
              required: ["invoice_id", "amount_cents"],
            },
          },
        ],
      }),
    )
    .catch((err) => {
      if (warnedCloudRegistration) return;
      warnedCloudRegistration = true;
      const reason = err instanceof Error ? err.message : String(err);
      console.warn(`KIFF Cloud registration failed: ${reason}`);
    });
}

export default definePluginEntry({
  id: "kiff-guard-demo",
  name: "KIFF Guard Demo",
  description: "Pay-invoice tool gated by KIFF clearance (before_tool_call).",
  register(api: any) {
    refreshCloudConnection();
    if (cloudGuard) setInterval(refreshCloudConnection, 60_000);

    // 1. The gate: every before_tool_call goes through KIFF.
    api.on("before_tool_call", kiffBeforeToolCall(guard), { priority: 50 });

    // 2. The tool the agent calls. Executes the real debit against ap-app.
    api.registerTool(
      {
        name: "pay_invoice",
        label: "Pay invoice",
        description:
          "Pay an outstanding invoice by id. Debits the account and marks the invoice paid.",
        parameters: {
          type: "object",
          additionalProperties: false,
          properties: {
            invoice_id: { type: "string", description: "The invoice id to pay, e.g. inv-001." },
            amount_cents: { type: "integer", description: "Amount in cents." },
          },
          required: ["invoice_id"],
        },
        async execute(_id: string, params: { invoice_id: string; amount_cents?: number }) {
          // If we reach here, KIFF cleared the call. Perform the debit.
          const resp = await fetch(`${AP_APP}/pay`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ invoice_id: params.invoice_id }),
          });
          const body = await resp.json();
          if (!resp.ok) {
            return `payment failed: ${JSON.stringify(body)}`;
          }
          return `paid ${body.invoice_id}: debit #${body.debit_number}, ${body.amount_cents} cents`;
        },
      },
    );
  },
});
