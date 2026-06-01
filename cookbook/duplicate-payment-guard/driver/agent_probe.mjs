import { Gateway } from "./ocgw.mjs";

const URL = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";

const gw = new Gateway({ url: URL, token: TOKEN });
gw.onEvent((f) => {
  // print agent/tool lifecycle events as they stream
  const ev = f.event || "";
  if (/agent|tool|run|assistant|message/.test(ev)) {
    console.log("EVENT", ev, JSON.stringify(f.payload || {}).slice(0, 160));
  }
});
await gw.connect();
console.log("connected");

try {
  const r = await gw.request("agent", {
    agentId: "main",
    sessionKey: "ap-demo",
    message: "Reply with exactly the word PONG.",
    model: "openai/gpt-4o-mini",
    idempotencyKey: "probe-" + Date.now(),
  }, 90000);
  console.log("AGENT RESULT:", JSON.stringify(r).slice(0, 400));
} catch (e) {
  console.log("agent err:", (e.message || e).slice(0, 200));
}

gw.close();
process.exit(0);
