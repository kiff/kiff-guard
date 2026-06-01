// rpc_probe.mjs — discover the gateway's agent-run RPC by trying the
// documented method names against the live gateway and printing what
// comes back. Low-level: openclaw-sdk is a transport (connect + request).
import { OpenClawClient } from "openclaw-sdk";

const URL = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";

const client = new OpenClawClient({
  url: URL,
  clientId: "cli",
  clientVersion: "0.1.0",
  auth: { token: TOKEN },
});
client.onError?.((e) => console.error("client error:", e?.message || e));
await client.connect();
console.log("connected:", client.isConnected?.());

async function tryMethod(method, params) {
  try {
    const res = await client.request(method, params, { timeoutMs: 8000 });
    console.log(`OK   ${method} ->`, JSON.stringify(res).slice(0, 300));
    return res;
  } catch (e) {
    console.log(`FAIL ${method} ->`, (e?.message || String(e)).slice(0, 160));
    return null;
  }
}

// Probe likely introspection + agent-run methods.
await tryMethod("rpc.methods", {});
await tryMethod("methods.list", {});
await tryMethod("models.list", {});
await tryMethod("agents.list", {});
await tryMethod("agent.list", {});
await tryMethod("tools.list", {});

await client.disconnect?.();
process.exit(0);
