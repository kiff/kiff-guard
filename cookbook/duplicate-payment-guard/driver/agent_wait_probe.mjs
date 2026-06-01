import { Gateway } from "./ocgw.mjs";

const URL = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";

const gw = new Gateway({ url: URL, token: TOKEN });
const seen = new Set();
gw.onEvent((f) => {
  if (!seen.has(f.event)) { seen.add(f.event); }
  console.log("EVENT", f.event, JSON.stringify(f.payload || {}).slice(0, 140));
});
await gw.connect();

const runId = "probe-" + Date.now();
const acc = await gw.request("agent", {
  agentId: "main", sessionKey: "ap-demo",
  message: "Reply with exactly the word PONG.",
  model: "openai/gpt-4o-mini", idempotencyKey: runId,
}, 30000);
console.log("accepted:", JSON.stringify(acc));

// Wait for the run to finish.
try {
  const res = await gw.request("agent.wait", { runId: acc.runId }, 90000);
  console.log("WAIT RESULT:", JSON.stringify(res).slice(0, 400));
} catch (e) {
  console.log("agent.wait err:", (e.message || e).slice(0, 160));
}

console.log("\nevent types seen:", [...seen]);
gw.close();
process.exit(0);
