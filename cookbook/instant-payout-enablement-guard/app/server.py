"""payout-app — system of record for escrow disbursements.

/escrow    — create an escrow
/clear     — mark escrow cleared (dispute resolved, funds ready)
/disburse  — execute the payout (non-idempotent: pays out on every call)
/ledger    — stats
/reset     — reset
/healthz
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_escrows: dict = {}
_stats = {"disbursements": 0, "disbursed_cents": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {"escrows": dict(_escrows), **_stats})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/escrow":
            self._create(body)
        elif self.path == "/clear":
            self._clear(body)
        elif self.path == "/disburse":
            self._disburse(body)
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _create(self, body):
        escrow_id = body.get("escrow_id", "")
        amount = body.get("amount_cents", 0)
        seller_id = body.get("seller_id", "seller-001")
        if not escrow_id:
            self._json(400, {"error": "escrow_id required"})
            return
        with _lock:
            _escrows[escrow_id] = {"amount_cents": amount, "seller_id": seller_id,
                                   "cleared": False, "disbursements": []}
        self._json(201, {"status": "created", "escrow_id": escrow_id})

    def _clear(self, body):
        escrow_id = body.get("escrow_id", "")
        with _lock:
            e = _escrows.get(escrow_id)
            if not e:
                self._json(404, {"error": f"escrow {escrow_id} not found"})
                return
            e["cleared"] = True
        self._json(200, {"status": "cleared", "escrow_id": escrow_id})

    def _disburse(self, body):
        escrow_id = body.get("escrow_id", "")
        amount = body.get("amount_cents", 0)
        seller_id = body.get("seller_id", "")
        if not escrow_id:
            self._json(400, {"error": "escrow_id required"})
            return
        with _lock:
            e = _escrows.get(escrow_id)
            if not e:
                self._json(404, {"error": f"escrow {escrow_id} not found"})
                return
            n = len(e["disbursements"]) + 1
            e["disbursements"].append({"amount_cents": amount, "seller_id": seller_id, "number": n})
            _stats["disbursements"] += 1
            _stats["disbursed_cents"] += amount
        self._json(200, {"status": "disbursed", "escrow_id": escrow_id,
                         "amount_cents": amount, "disbursement_number": n})

    def _reset(self, body):
        escrow_id = body.get("escrow_id", "")
        with _lock:
            if escrow_id and escrow_id in _escrows:
                del _escrows[escrow_id]
            elif not escrow_id:
                _escrows.clear()
            _stats["disbursements"] = 0
            _stats["disbursed_cents"] = 0
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
    port = 8082
    print(f"payout-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
