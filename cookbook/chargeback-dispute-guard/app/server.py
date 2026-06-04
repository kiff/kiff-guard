"""disputes-app — system of record for chargebacks.

/dispute        create a dispute
/submit         submit a chargeback to card scheme (non-idempotent)
/ledger         stats
/reset          reset
/healthz
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_disputes: dict = {}
_stats = {"total_submissions": 0, "total_fees_cents": 0}
SCHEME_FEE_CENTS = 2500  # $25 per submission to card scheme


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {"disputes": dict(_disputes), **_stats,
                                 "total_fees_usd": f"{_stats['total_fees_cents']/100:.2f}"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/dispute":
            self._create(body)
        elif self.path == "/submit":
            self._submit(body)
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _create(self, body):
        dispute_id = body.get("dispute_id", "")
        amount = body.get("amount_cents", 0)
        reason = body.get("reason_code", "")
        if not dispute_id:
            self._json(400, {"error": "dispute_id required"})
            return
        with _lock:
            _disputes[dispute_id] = {"amount_cents": amount, "reason_code": reason, "submissions": []}
        self._json(201, {"status": "created", "dispute_id": dispute_id})

    def _submit(self, body):
        dispute_id = body.get("dispute_id", "")
        reason_code = body.get("reason_code", "")
        amount = body.get("amount_cents", 0)
        if not dispute_id:
            self._json(400, {"error": "dispute_id required"})
            return
        with _lock:
            dispute = _disputes.get(dispute_id)
            if not dispute:
                self._json(404, {"error": f"dispute {dispute_id} not found"})
                return
            sub_number = len(dispute["submissions"]) + 1
            dispute["submissions"].append({"reason_code": reason_code, "amount_cents": amount, "number": sub_number})
            _stats["total_submissions"] += 1
            _stats["total_fees_cents"] += SCHEME_FEE_CENTS
        self._json(200, {"status": "submitted", "dispute_id": dispute_id,
                         "submission_number": sub_number, "scheme_fee_cents": SCHEME_FEE_CENTS})

    def _reset(self, body):
        dispute_id = body.get("dispute_id", "")
        with _lock:
            if dispute_id and dispute_id in _disputes:
                del _disputes[dispute_id]
            elif not dispute_id:
                _disputes.clear()
            _stats["total_submissions"] = 0
            _stats["total_fees_cents"] = 0
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
    print(f"disputes-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
