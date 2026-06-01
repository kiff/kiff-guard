import { Gateway } from "./ocgw.mjs";

const URL = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";

const gw = new Gateway({ url: URL, token: TOKEN });
await gw.connect();
console.log("connected (operator.admin)");

async function probe(method, params) {
  try {
    const r = await gw.request(method, params, 10000);
    console.log(`OK   ${method} -> ${JSON.stringify(r).slice(0, 200)}`);
    return r;
  } catch (e) {
    console.log(`FAIL ${method} -> ${(e.message || e).slice(0, 140)}`);
    return null;
  }
}

console.log("\n-- tools --");
await probe("tools.list", {});
await probe("tools.effective", { sessionKey: "ap-demo" });

console.log("\n-- agent run candidates --");
await probe("sessions.send", { agentId: "main", sessionKey: "ap-demo", input: "Reply with PONG only." });
await probe("agent", { agentId: "main", sessionKey: "ap-demo", input: "Reply with PONG only.", model: "openai/gpt-4o-mini" });

gw.close();
process.exit(0);
