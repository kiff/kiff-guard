// ap-app — the system of record for the duplicate-payment-guard recipe.
//
// It holds invoices and a ledger, and exposes /pay. This is the service
// whose state must NOT move when KIFF blocks a retry — the honest proof
// that the gate stopped a real side effect.
//
// IMPORTANT: ap-app does NOT call KIFF. The gate sits in front of the
// *tool* (in OpenClaw's before_tool_call). ap-app just performs the
// debit when asked and reports its ledger. That separation is the point:
// if a duplicate /pay reaches ap-app, it WILL debit again — so the only
// thing preventing $100k is the gate refusing to call /pay a second time.
//
// To keep the demo honest about state, /pay is deliberately NOT
// idempotent: a real AP system that double-pays on a retry is exactly
// the failure we are demonstrating. After a successful debit, ap-app
// tells the gate to advance the invoice to PAID (ingest INVOICE_PAID),
// so the gate's next decide on a retry returns state_not_allowed.
//
// Node stdlib only (http) — no deps, so the container is tiny.

import http from "node:http";

const PORT = parseInt(process.env.PORT || "8082", 10);
const KIFF_BASE = (process.env.KIFF_BASE_URL || "http://localhost:8081").replace(/\/+$/, "");

// ---- in-memory system of record ----
/** @type {Map<string, {id:string, amountCents:number, status:string}>} */
const invoices = new Map();
/** @type {Array<{invoiceId:string, amountCents:number, ts:string}>} */
const ledger = [];

function seedInvoice(id, amountCents) {
  invoices.set(id, { id, amountCents, status: "PENDING" });
}
// One invoice the scenario pays. $10,000.00 = 1,000,000 cents.
seedInvoice("inv-001", 1000000);

function totalPaidCents() {
  return ledger.reduce((sum, e) => sum + e.amountCents, 0);
}

async function ingestPaidToKiff(invoiceId, amountCents) {
  // Tell the gate a real debit happened so the invoice advances to PAID.
  const body = JSON.stringify({
    invoice_id: invoiceId,
    type: "INVOICE_PAID",
    actor_id: "ap-app",
    payload: { amount_cents: amountCents },
  });
  try {
    await fetch(`${KIFF_BASE}/v1/events/raw`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch (err) {
    // Non-fatal for the demo: the debit already happened; log it.
    console.error(`ap-app: failed to advance state in KIFF: ${err}`);
  }
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve(null);
      }
    });
  });
}

function send(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (req.method === "GET" && url.pathname === "/healthz") {
    return send(res, 200, { status: "ok" });
  }

  // The ledger + invoice state — the proof surface.
  if (req.method === "GET" && url.pathname === "/ledger") {
    return send(res, 200, {
      total_paid_cents: totalPaidCents(),
      total_paid_usd: (totalPaidCents() / 100).toFixed(2),
      debits: ledger.length,
      entries: ledger,
      invoices: [...invoices.values()],
    });
  }

  // Reset between scenario runs (the driver calls this). Optionally
  // seed a specific invoice id so each phase uses an independent entity.
  if (req.method === "POST" && url.pathname === "/reset") {
    const body = await readBody(req);
    ledger.length = 0;
    invoices.clear();
    const id = body && body.invoice_id ? body.invoice_id : "inv-001";
    seedInvoice(id, 1000000);
    return send(res, 200, { status: "reset", invoice_id: id });
  }

  // The real side effect. NOT idempotent by design.
  if (req.method === "POST" && url.pathname === "/pay") {
    const body = await readBody(req);
    if (!body || !body.invoice_id) {
      return send(res, 400, { error: "invoice_id required" });
    }
    let inv = invoices.get(body.invoice_id);
    if (!inv) {
      // Unknown invoice: register it on first pay so the demo's
      // independent per-phase ids work without a prior seed call.
      seedInvoice(body.invoice_id, 1000000);
      inv = invoices.get(body.invoice_id);
    }
    // Debit. A real AP system here would call the bank. We append to the
    // ledger every time we are asked — that is the danger being shown.
    ledger.push({ invoiceId: inv.id, amountCents: inv.amountCents, ts: new Date().toISOString() });
    inv.status = "PAID";
    await ingestPaidToKiff(inv.id, inv.amountCents);
    return send(res, 200, {
      status: "paid",
      invoice_id: inv.id,
      amount_cents: inv.amountCents,
      debit_number: ledger.length,
    });
  }

  send(res, 404, { error: "not found" });
});

server.listen(PORT, () => {
  console.log(`ap-app (system of record) on :${PORT}; KIFF at ${KIFF_BASE}`);
});
