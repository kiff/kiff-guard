import { Gateway } from "./ocgw.mjs";

const URL = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";

const gw = new Gateway({ url: URL, token: TOKEN });
const hello = await gw.connect();
console.log("HANDSHAKE OK. hello-ok keys:", Object.keys(hello || {}));
console.log("auth:", JSON.stringify(hello?.auth || {}).slice(0, 200));

// Try a few read methods to discover the agent-run surface.
for (const m of ["models.list", "tools.list", "agents.list", "agent.list", "sessions.list"]) {
  try {
    const r = await gw.request(m, {}, 8000);
    const s = JSON.stringify(r);
    console.log(`OK   ${m} -> ${s.slice(0, 160)}`);
  } catch (e) {
    console.log(`FAIL ${m} -> ${(e.message || e).slice(0, 100)}`);
  }
}
gw.close();
process.exit(0);
