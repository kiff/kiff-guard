import { Gateway } from "./ocgw.mjs";

const URL = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";

const gw = new Gateway({ url: URL, token: TOKEN });
await gw.connect();

async function probe(label, params) {
  try {
    const r = await gw.request("tools.invoke", params, 15000);
    console.log(`OK   [${label}] -> ${JSON.stringify(r).slice(0, 300)}`);
    return r;
  } catch (e) {
    console.log(`FAIL [${label}] -> ${(e.message || e).slice(0, 200)}`);
    return null;
  }
}

const a = { invoice_id: "inv-probe", amount_cents: 1000000 };
await probe("params", { name: "pay_invoice", params: a, sessionKey: "ap-demo" });
await probe("input", { name: "pay_invoice", input: a, sessionKey: "ap-demo" });
await probe("args+agentId", { name: "pay_invoice", args: a, sessionKey: "ap-demo", agentId: "main" });
await probe("toolId", { toolId: "pay_invoice", params: a, sessionKey: "ap-demo" });
await probe("id", { id: "pay_invoice", params: a, sessionKey: "ap-demo" });
await probe("tool+params", { tool: "pay_invoice", params: a, sessionKey: "ap-demo" });

gw.close();
process.exit(0);
