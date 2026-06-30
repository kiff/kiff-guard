"""deal-app — system of record for sales deals.

/deal      — create a deal
/qualify   — mark a deal qualified/open (the state that precedes a discount)
/discount  — apply a discount (non-idempotent: stacks on every call)
/ledger    — current stats
/reset     — reset
/healthz

Deliberately non-idempotent: /discount stacks a new discount every time it
is called, so the WITHOUT-KIFF baseline destroys margin by stacking, and the
WITH-KIFF run shows the boundary letting the legitimate closing discount
through and declining the repeat.
"""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_deals: dict = {}
_stats = {"discounts": 0, "discount_bps": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {"deals": dict(_deals), **_stats})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/deal":
            self._create_deal(body)
        elif self.path == "/qualify":
            self._qualify(body)
        elif self.path == "/discount":
            self._discount(body)
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _create_deal(self, body):
        deal_id = body.get("deal_id", "")
        value = body.get("value_cents", 0)
        if not deal_id:
            self._json(400, {"error": "deal_id required"})
            return
        with _lock:
            _deals[deal_id] = {"value_cents": value, "open": False, "discounts": []}
        self._json(201, {"status": "created", "deal_id": deal_id})

    def _qualify(self, body):
        deal_id = body.get("deal_id", "")
        with _lock:
            deal = _deals.get(deal_id)
            if not deal:
                self._json(404, {"error": f"deal {deal_id} not found"})
                return
            deal["open"] = True
        self._json(200, {"status": "open", "deal_id": deal_id})

    def _discount(self, body):
        deal_id = body.get("deal_id", "")
        percent = body.get("percent", 0)
        if not deal_id:
            self._json(400, {"error": "deal_id required"})
            return
        with _lock:
            deal = _deals.get(deal_id)
            if not deal:
                self._json(404, {"error": f"deal {deal_id} not found"})
                return
            discount_number = len(deal["discounts"]) + 1
            deal["discounts"].append({"percent": percent, "number": discount_number})
            _stats["discounts"] += 1
            _stats["discount_bps"] += int(percent) * 100
        self._json(200, {"status": "discounted", "deal_id": deal_id,
                         "percent": percent, "discount_number": discount_number})

    def _reset(self, body):
        deal_id = body.get("deal_id", "")
        with _lock:
            if deal_id and deal_id in _deals:
                del _deals[deal_id]
            elif not deal_id:
                _deals.clear()
            _stats["discounts"] = 0
            _stats["discount_bps"] = 0
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
    print(f"deal-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
