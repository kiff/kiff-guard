"""collections-app — system of record for delinquent cases.

/contact  — log a contact attempt (non-idempotent: logs every call)
/promise  — record a promise to pay (advances state externally)
/case     — create a case
/ledger   — current stats
/reset    — reset
/healthz
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_cases: dict = {}
_stats = {"total_contacts": 0, "promises": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {"cases": dict(_cases), **_stats})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/case":
            self._create_case(body)
        elif self.path == "/contact":
            self._contact(body)
        elif self.path == "/promise":
            self._promise(body)
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _create_case(self, body):
        case_id = body.get("case_id", "")
        borrower = body.get("borrower", "unknown")
        balance = body.get("balance_cents", 0)
        if not case_id:
            self._json(400, {"error": "case_id required"})
            return
        with _lock:
            _cases[case_id] = {"borrower": borrower, "balance_cents": balance,
                               "contacts": [], "promise": None}
        self._json(201, {"status": "created", "case_id": case_id})

    def _contact(self, body):
        case_id = body.get("case_id", "")
        channel = body.get("channel", "sms")
        if not case_id:
            self._json(400, {"error": "case_id required"})
            return
        with _lock:
            case = _cases.get(case_id)
            if not case:
                self._json(404, {"error": f"case {case_id} not found"})
                return
            contact_number = len(case["contacts"]) + 1
            case["contacts"].append({"channel": channel, "number": contact_number})
            _stats["total_contacts"] += 1
        self._json(200, {"status": "contacted", "case_id": case_id,
                         "channel": channel, "contact_number": contact_number})

    def _promise(self, body):
        case_id = body.get("case_id", "")
        amount = body.get("amount_cents", 0)
        pay_date = body.get("pay_date", "")
        if not case_id:
            self._json(400, {"error": "case_id required"})
            return
        with _lock:
            case = _cases.get(case_id)
            if not case:
                self._json(404, {"error": f"case {case_id} not found"})
                return
            case["promise"] = {"amount_cents": amount, "pay_date": pay_date}
            _stats["promises"] += 1
        self._json(200, {"status": "promise_recorded", "case_id": case_id})

    def _reset(self, body):
        case_id = body.get("case_id", "")
        with _lock:
            if case_id and case_id in _cases:
                del _cases[case_id]
            elif not case_id:
                _cases.clear()
            _stats["total_contacts"] = 0
            _stats["promises"] = 0
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
    print(f"collections-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
