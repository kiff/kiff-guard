// connect_check.mjs — prove the App SDK can drive a real agent turn
// through the gateway on the real model. No tool yet; just confirm the
// model responds, so we know the gateway + provider + SDK path works
// before layering the plugin.
import { OpenClaw } from "@openclaw/sdk";

const GATEWAY = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";
const MODEL = process.env.KIFF_COOKBOOK_MODEL || "openai/gpt-4o-mini";

const oc = new OpenClaw({ url: GATEWAY, token: TOKEN, requestTimeoutMs: 60_000 });
await oc.connect();
console.log("connected to gateway");

const agent = await oc.agents.get("main");
const run = await agent.run({
  input: "Reply with exactly the word: PONG",
  model: MODEL,
  sessionKey: "connect-check",
  timeoutMs: 60_000,
});

let text = "";
for await (const ev of run.events()) {
  const d = ev.data || {};
  if (ev.type === "assistant.delta" && typeof d.delta === "string") text += d.delta;
  if (ev.type === "assistant.message" && typeof d.text === "string") text = d.text;
  if (ev.type === "run.completed" || ev.type === "run.failed" || ev.type === "run.timed_out") {
    console.log("run end:", ev.type);
    break;
  }
}
console.log("model said:", JSON.stringify(text.trim().slice(0, 120)));
const res = await run.wait({ timeoutMs: 60_000 });
console.log("status:", res.status);
process.exit(0);
