// gate_proof.mjs — proves the gate + ap-app loop without OpenClaw.
//
// Models the retry storm at the tool seam: each "attempt" first asks
// KIFF to decide (as the before_tool_call hook would), and only calls
// ap-app /pay if KIFF says allowed. This is exactly what the OpenClaw
// adapter does — here without the gateway, so we can prove the
// gate+app loop on its own.
//
//   WITHOUT KIFF: call /pay N times directly -> N debits.
//   WITH KIFF:    decide before each /pay -> 1 allowed, N-1 blocked.
//
// Each phase uses its OWN invoice id so the runs are independent (the
// gate's invoice state advances to PAID after a real debit, which is the
// whole point — so the two phases must not share an entity).

const KIFF = process.env.KIFF_BASE_URL || "http://localhost:8081";
const AP = process.env.AP_APP_URL || "http://localhost:8082";
const N = parseInt(process.env.RETRY_COUNT || "10", 10);
const RUN = Date.now();

async function j(url, method = "GET", body) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

async function decide(invoiceId) {
  return j(`${KIFF}/v1/proposals/decide`, "POST", {
    entity_id: invoiceId,
    entity_type: "Invoice",
    action_name: "PAY_INVOICE",
    actor_id: "ap-agent",
    parameters: { amount_cents: 1000000 },
  });
}

function banner(t) {
  console.log("\n" + "=".repeat(60) + "\n  " + t + "\n" + "=".repeat(60));
}

async function withoutKiff() {
  banner("WITHOUT KIFF — every retry debits");
  const inv = `inv-nokiff-${RUN}`;
  await j(`${AP}/reset`, "POST", { invoice_id: inv });
  await j(`${KIFF}/seed`, "POST", { invoice_id: inv });
  for (let i = 1; i <= N; i++) {
    const r = await j(`${AP}/pay`, "POST", { invoice_id: inv });
    console.log(`  attempt ${i}: debit #${r.debit_number}`);
  }
  const l = await j(`${AP}/ledger`);
  console.log(`  RESULT: $${l.total_paid_usd} across ${l.debits} debits`);
  return l;
}

async function withKiff() {
  banner("WITH KIFF — gate stops the duplicates");
  const inv = `inv-kiff-${RUN}`;
  await j(`${AP}/reset`, "POST", { invoice_id: inv });
  await j(`${KIFF}/seed`, "POST", { invoice_id: inv });
  let blocked = 0;
  for (let i = 1; i <= N; i++) {
    const d = await decide(inv);
    if (d.outcome === "allowed") {
      const r = await j(`${AP}/pay`, "POST", { invoice_id: inv });
      console.log(`  attempt ${i}: KIFF allowed -> debit #${r.debit_number}`);
    } else {
      blocked++;
      console.log(`  attempt ${i}: KIFF ${d.outcome} (${(d.reasons || []).join(",")}) -> NOT paid`);
    }
  }
  const l = await j(`${AP}/ledger`);
  console.log(`  RESULT: $${l.total_paid_usd} across ${l.debits} debit; ${blocked} blocked`);
  return l;
}

const a = await withoutKiff();
const b = await withKiff();
banner("VERDICT");
console.log(`  WITHOUT KIFF : $${a.total_paid_usd}  (${a.debits} debits)`);
console.log(`  WITH KIFF    : $${b.total_paid_usd}  (${b.debits} debit)`);
const pass = a.debits === N && b.debits === 1;
console.log(pass ? "\n  PROOF PASSED: only a state-aware gate stops the repeat. ✅" : "\n  UNEXPECTED ❌");
process.exit(pass ? 0 : 1);
