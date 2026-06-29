"""refund-app — system of record for orders.

/order    — create an order
/pay      — mark an order paid (the side effect that precedes a refund)
/refund   — issue a refund (non-idempotent: pays out on every call)
/ledger   — current stats
/reset    — reset
/healthz

Deliberately non-idempotent: /refund pays out every time it is called,
so the WITHOUT-KIFF baseline double-pays and the WITH-KIFF run shows the
boundary letting the legitimate refund through and declining the repeat.
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_orders: dict = {}
_stats = {"refunds": 0, "refunded_cents": 0}


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
            self._create_order(body)
        elif self.path == "/pay":
            self._pay(body)
        elif self.path == "/refund":
            self._refund(body)
        elif self.path == "/reset":
            self._reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _create_order(self, body):
        order_id = body.get("order_id", "")
        total = body.get("total_cents", 0)
        if not order_id:
            self._json(400, {"error": "order_id required"})
            return
        with _lock:
            _orders[order_id] = {"total_cents": total, "paid": False,
                                 "refunds": []}
        self._json(201, {"status": "created", "order_id": order_id})

    def _pay(self, body):
        order_id = body.get("order_id", "")
        with _lock:
            order = _orders.get(order_id)
            if not order:
                self._json(404, {"error": f"order {order_id} not found"})
                return
            order["paid"] = True
        self._json(200, {"status": "paid", "order_id": order_id})

    def _refund(self, body):
        order_id = body.get("order_id", "")
        amount = body.get("amount_cents", 0)
        if not order_id:
            self._json(400, {"error": "order_id required"})
            return
        with _lock:
            order = _orders.get(order_id)
            if not order:
                self._json(404, {"error": f"order {order_id} not found"})
                return
            refund_number = len(order["refunds"]) + 1
            order["refunds"].append({"amount_cents": amount, "number": refund_number})
            _stats["refunds"] += 1
            _stats["refunded_cents"] += amount
        self._json(200, {"status": "refunded", "order_id": order_id,
                         "amount_cents": amount, "refund_number": refund_number})

    def _reset(self, body):
        order_id = body.get("order_id", "")
        with _lock:
            if order_id and order_id in _orders:
                del _orders[order_id]
            elif not order_id:
                _orders.clear()
            _stats["refunds"] = 0
            _stats["refunded_cents"] = 0
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
    print(f"refund-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
