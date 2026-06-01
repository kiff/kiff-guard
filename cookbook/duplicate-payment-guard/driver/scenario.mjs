// scenario.mjs — the side-by-side proof.
//
// Runs the duplicate-payment scenario twice and prints the ledger each
// time:
//
//   WITHOUT KIFF: the flaky connection makes the payment retry N times;
//     ap-app debits every time -> $100,000, N debits. (No gate at all —
//     calls ap-app /pay directly, the honest ungoverned baseline.)
//   WITH KIFF: the same storm, but every tool call passes through
//     OpenClaw's before_tool_call -> KIFF. KIFF allows the first (invoice
//     PENDING) and blocks every retry (invoice now PAID) -> $10,000,
//     1 debit, N-1 blocked.
//
// The WITH-KIFF first payment is driven by the REAL OpenClaw agent (a
// real gpt-4o-mini turn) calling the pay_invoice tool, proving the
// model + plugin + gate path end to end. The retry storm then re-invokes
// the SAME guarded tool seam (tools.invoke) N-1 times — each call goes
// through before_tool_call -> KIFF. The gate, not the app, stops them.
//
// Transport: the raw-WS gateway client in ./ocgw.mjs (the published
// openclaw-sdk is pinned to an older protocol and no longer handshakes).

import { Gateway } from "./ocgw.mjs";

const AP_APP = process.env.AP_APP_URL || "http://localhost:8082";
const KIFF = process.env.KIFF_BASE_URL || "http://localhost:8081";
const GATEWAY = process.env.OPENCLAW_GATEWAY_URL || "ws://127.0.0.1:18789";
const TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN || "";
const MODEL = process.env.KIFF_COOKBOOK_MODEL || "openai/gpt-4o-mini";
const RETRIES = parseInt(process.env.RETRY_COUNT || "10", 10);
const AMOUNT = 1000000; // $10,000.00

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function j(url, method = "GET", body) {
  const resp = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return resp.json();
}

const ap = (path, method, body) => j(`${AP_APP}${path}`, method, body);
const ledger = () => ap("/ledger");

function banner(title) {
  console.log("\n" + "=".repeat(66) + "\n  " + title + "\n" + "=".repeat(66));
}

// ---- Run A: no gate. The raw retry storm. ----
async function runWithoutKiff(inv) {
  banner("WITHOUT KIFF — ungoverned: every retry debits");
  await ap("/reset", "POST", { invoice_id: inv });
  console.log(`flaky connection: the $10,000 payment 'fails' to ack and retries ${RETRIES}x...`);
  for (let i = 1; i <= RETRIES; i++) {
    const r = await ap("/pay", "POST", { invoice_id: inv });
    console.log(`  attempt ${i}: ap-app debited (#${r.debit_number})`);
  }
  const l = await ledger();
  console.log(`\n  RESULT: $${l.total_paid_usd} paid across ${l.debits} debits.`);
  return l;
}

// ---- Run B: with KIFF, through the real OpenClaw agent. ----
async function runWithKiff(inv) {
  banner("WITH KIFF — the gate stops the duplicates");
  // Independent entity for this phase: seed PENDING in BOTH the gate and
  // the system of record.
  await ap("/reset", "POST", { invoice_id: inv });
  await j(`${KIFF}/seed`, "POST", { invoice_id: inv });

  const gw = new Gateway({ url: GATEWAY, token: TOKEN });
  await gw.connect();

  // 1) One real LLM-driven attempt: ask the agent to pay the invoice.
  //    The agent calls pay_invoice -> before_tool_call -> KIFF (PENDING
  //    -> allowed) -> tool executes -> ap-app debits -> state advances.
  console.log(`agent (real ${MODEL}) is asked to pay invoice ${inv} ($10,000)...`);
  const runId = "pay-" + Date.now();
  const acc = await gw.request("agent", {
    agentId: "main",
    sessionKey: "ap-demo",
    message:
      `Pay invoice ${inv} using the pay_invoice tool. ` +
      `The amount is ${AMOUNT} cents. Call the tool exactly once, then stop.`,
    model: MODEL,
    idempotencyKey: runId,
  }, 60000);
  try {
    await gw.request("agent.wait", { runId: acc.runId }, 90000);
  } catch (e) {
    console.log("  (agent.wait note:", (e.message || e).slice(0, 80) + ")");
  }
  const afterAgent = await ledger();
  console.log(`  first attempt via the agent: ${afterAgent.debits === 1 ? "EXECUTED (KIFF allowed, invoice PENDING)" : `debits=${afterAgent.debits}`}`);

  // 2) The transport retry storm: re-invoke the SAME guarded tool seam.
  //    Each call goes through before_tool_call -> KIFF. The invoice is
  //    now PAID, so KIFF blocks every one (state_not_allowed).
  console.log(`flaky connection: retrying the same tool call ${RETRIES - 1}x...`);
  let blocked = 0;
  for (let i = 2; i <= RETRIES; i++) {
    const res = await gw.request("tools.invoke", {
      name: "pay_invoice",
      args: { invoice_id: inv, amount_cents: AMOUNT },
      sessionKey: "ap-demo",
      agentId: "main",
    }, 30000);
    const ok = res && res.ok === true;
    if (!ok) blocked++;
    const why = res?.error?.message ? ` (${res.error.message.replace(/\s+/g, " ").slice(0, 60)})` : "";
    console.log(`  retry ${i}: ${ok ? "EXECUTED (!!)" : "blocked by KIFF"}${ok ? "" : why}`);
  }

  const l = await ledger();
  console.log(`\n  RESULT: $${l.total_paid_usd} paid across ${l.debits} debit(s); ${blocked} retries blocked by KIFF.`);
  gw.close();
  return l;
}

async function main() {
  const stamp = Date.now();
  const a = await runWithoutKiff(`inv-nokiff-${stamp}`);
  await sleep(500);
  const b = await runWithKiff(`inv-kiff-${stamp}`);

  banner("VERDICT");
  console.log(`  WITHOUT KIFF : $${a.total_paid_usd}  (${a.debits} debits)   FAIL`);
  console.log(`  WITH KIFF    : $${b.total_paid_usd}  (${b.debits} debit)    PASS`);
  console.log("");
  const pass = b.debits === 1 && a.debits === RETRIES;
  console.log(pass
    ? "  PROOF: every individual $10k call was legitimate. Only a state-aware gate stopped the repeat."
    : "  UNEXPECTED: see ledger output above.");
  process.exit(pass ? 0 : 1);
}

main().catch((e) => {
  console.error("scenario error:", e);
  process.exit(2);
});
