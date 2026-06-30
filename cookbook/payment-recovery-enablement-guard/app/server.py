"""payment-app — system of record for invoices.

/invoice   — create an invoice
/fail      — mark an invoice past due (the state that precedes a retry)
/charge    — retry the charge (non-idempotent: hits the card on every call)
/ledger    — current stats
/reset     — reset
/healthz

Deliberately non-idempotent: /charge hits the card every time it is called,
so the WITHOUT-KIFF baseline hammers the customer's card, and the WITH-KIFF
run shows the boundary letting the legitimate recovery charge through and
declining the repeats.
"""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_invoices: dict = {}
_stats = {"charges": 0, "charged_cents": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {"invoices": dict(_invoices), **_stats})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/invoice":
            self._create(body)
        elif self.path == "/fail":
            self._fail(body)
        elif self.path == "/charge":
            self._charge(body)
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _create(self, body):
        invoice_id = body.get("invoice_id", "")
        amount = body.get("amount_cents", 0)
        if not invoice_id:
            self._json(400, {"error": "invoice_id required"})
            return
        with _lock:
            _invoices[invoice_id] = {"amount_cents": amount, "past_due": False, "charges": []}
        self._json(201, {"status": "created", "invoice_id": invoice_id})

    def _fail(self, body):
        invoice_id = body.get("invoice_id", "")
        with _lock:
            inv = _invoices.get(invoice_id)
            if not inv:
                self._json(404, {"error": f"invoice {invoice_id} not found"})
                return
            inv["past_due"] = True
        self._json(200, {"status": "past_due", "invoice_id": invoice_id})

    def _charge(self, body):
        invoice_id = body.get("invoice_id", "")
        amount = body.get("amount_cents", 0)
        if not invoice_id:
            self._json(400, {"error": "invoice_id required"})
            return
        with _lock:
            inv = _invoices.get(invoice_id)
            if not inv:
                self._json(404, {"error": f"invoice {invoice_id} not found"})
                return
            charge_number = len(inv["charges"]) + 1
            inv["charges"].append({"amount_cents": amount, "number": charge_number})
            _stats["charges"] += 1
            _stats["charged_cents"] += amount
        self._json(200, {"status": "charged", "invoice_id": invoice_id,
                         "amount_cents": amount, "charge_number": charge_number})

    def _reset(self, body):
        invoice_id = body.get("invoice_id", "")
        with _lock:
            if invoice_id and invoice_id in _invoices:
                del _invoices[invoice_id]
            elif not invoice_id:
                _invoices.clear()
            _stats["charges"] = 0
            _stats["charged_cents"] = 0
        self._json(200, {"status": "reset"})

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "8082"))
    print(f"payment-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
