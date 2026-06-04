"""kyb-app — system of record for KYB (Know Your Business) onboarding.

/business — register a business for onboarding
/verify   — run a paid bureau verification (Companies House + sanctions +
            UBO screen). Deliberately non-idempotent and NOT free: every
            call charges a bureau fee and writes a fresh verification.
/ledger   — current stats (verifications + total fees)
/reset    — reset
/healthz
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

BUREAU_FEE_CENTS = 1200  # $12.00 per bureau check (Companies House + sanctions + UBO)

_lock = Lock()
_businesses: dict = {}
_stats = {"total_checks": 0, "total_fees_cents": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {"businesses": dict(_businesses), **_stats})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/business":
            self._register(body)
        elif self.path == "/verify":
            self._verify(body)
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _register(self, body):
        business_id = body.get("business_id", "")
        name = body.get("name", "unknown")
        reg = body.get("registration_number", "")
        if not business_id:
            self._json(400, {"error": "business_id required"})
            return
        with _lock:
            _businesses[business_id] = {"name": name, "registration_number": reg,
                                        "checks": []}
        self._json(201, {"status": "registered", "business_id": business_id})

    def _verify(self, body):
        business_id = body.get("business_id", "")
        reg = body.get("registration_number", "")
        if not business_id:
            self._json(400, {"error": "business_id required"})
            return
        with _lock:
            biz = _businesses.get(business_id)
            if not biz:
                self._json(404, {"error": f"business {business_id} not found"})
                return
            number = len(biz["checks"]) + 1
            biz["checks"].append({"number": number, "registration_number": reg})
            _stats["total_checks"] += 1
            _stats["total_fees_cents"] += BUREAU_FEE_CENTS
        self._json(200, {"status": "verified", "business_id": business_id,
                         "check_number": number, "bureau_fee_cents": BUREAU_FEE_CENTS})

    def _reset(self, body):
        business_id = body.get("business_id", "")
        with _lock:
            if business_id and business_id in _businesses:
                del _businesses[business_id]
            elif not business_id:
                _businesses.clear()
            _stats["total_checks"] = 0
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
    print(f"kyb-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
