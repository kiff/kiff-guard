import { Gateway } from "./ocgw.mjs";

const URL = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";

const gw = new Gateway({ url: URL, token: TOKEN });
await gw.connect();
console.log("connected");

// Does pay_invoice show up in the effective tool set?
const eff = await gw.request("tools.effective", { sessionKey: "ap-demo", agentId: "main" }, 10000);
const groups = eff.groups || [];
for (const g of groups) {
  for (const t of g.tools || []) {
    if (String(t.id).includes("pay") || String(t.label || "").toLowerCase().includes("invoice")) {
      console.log("FOUND TOOL:", g.id, JSON.stringify(t).slice(0, 200));
    }
  }
}
console.log("groups:", groups.map((g) => `${g.id}(${(g.tools || []).length})`).join(", "));

// Probe candidate direct tool-invocation methods.
async function probe(method, params) {
  try {
    const r = await gw.request(method, params, 12000);
    console.log(`OK   ${method} -> ${JSON.stringify(r).slice(0, 240)}`);
    return r;
  } catch (e) {
    console.log(`FAIL ${method} -> ${(e.message || e).slice(0, 160)}`);
    return null;
  }
}
console.log("\n-- tool invoke candidates --");
const args = { invoice_id: "inv-probe", amount_cents: 1000000 };
await probe("tools.invoke", { name: "pay_invoice", arguments: args, sessionKey: "ap-demo" });
await probe("tools.call", { name: "pay_invoice", arguments: args, sessionKey: "ap-demo" });
await probe("tool.invoke", { name: "pay_invoice", args, sessionKey: "ap-demo" });
await probe("tools.run", { name: "pay_invoice", arguments: args, sessionKey: "ap-demo" });

gw.close();
process.exit(0);
