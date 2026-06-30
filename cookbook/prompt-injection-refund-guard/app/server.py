"""order-app — system of record for orders, refunds, and credits.

/order    — create an order
/pay      — mark an order paid
/refund   — issue a refund (non-idempotent: pays out every call)
/credit   — issue a store credit (non-idempotent: grants every call)
/ledger   — stats
/reset    — reset
/healthz

Both /refund and /credit are deliberately non-idempotent: each call moves
money. The WITHOUT-KIFF baseline shows that a sufficiently persuasive
customer message can drive the agent to pay out a second refund (or a
fallback credit) it should never have; WITH KIFF those calls are refused at
the boundary because the order is already REFUNDED.
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_orders: dict = {}
_stats = {"refunds": 0, "refunded_cents": 0, "credits": 0, "credited_cents": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {"orders": dict(_orders), **_stats})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/order":
            self._create(body)
        elif self.path == "/pay":
            self._pay(body)
        elif self.path == "/refund":
            self._money(body, "refund")
        elif self.path == "/credit":
            self._money(body, "credit")
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _create(self, body):
        order_id = body.get("order_id", "")
        total = body.get("total_cents", 0)
        if not order_id:
            self._json(400, {"error": "order_id required"})
            return
        with _lock:
            _orders[order_id] = {"total_cents": total, "paid": False, "movements": []}
        self._json(201, {"status": "created", "order_id": order_id})

    def _pay(self, body):
        order_id = body.get("order_id", "")
        with _lock:
            o = _orders.get(order_id)
            if not o:
                self._json(404, {"error": f"order {order_id} not found"})
                return
            o["paid"] = True
        self._json(200, {"status": "paid", "order_id": order_id})

    def _money(self, body, kind):
        order_id = body.get("order_id", "")
        amount = body.get("amount_cents", 0)
        if not order_id:
            self._json(400, {"error": "order_id required"})
            return
        with _lock:
            o = _orders.get(order_id)
            if not o:
                self._json(404, {"error": f"order {order_id} not found"})
                return
            n = len([m for m in o["movements"] if m["kind"] == kind]) + 1
            o["movements"].append({"kind": kind, "amount_cents": amount, "number": n})
            _stats[kind + "s"] += 1
            _stats[kind + "ed_cents"] += amount
        self._json(200, {"status": kind + "ed", "order_id": order_id,
                         "amount_cents": amount, "number": n})

    def _reset(self, body):
        order_id = body.get("order_id", "")
        with _lock:
            if order_id and order_id in _orders:
                del _orders[order_id]
            elif not order_id:
                _orders.clear()
            for k in _stats:
                _stats[k] = 0
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
    print(f"order-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
