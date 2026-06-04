"""refund-app — the system of record for orders and refunds.

Deliberately NON-idempotent: every call to /refund credits money. If the
agent retries, money goes out again. This is the honest baseline that
makes the KIFF gate load-bearing.

Routes:
  POST /order       create an order (amount_cents)
  POST /refund      issue a refund (order_id, amount_cents)
  GET  /ledger      current ledger stats
  POST /reset       reset ledger for a new proof run
  GET  /healthz
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_lock = Lock()
_orders: dict = {}  # order_id -> {amount_cents, refunded_cents, refunds: []}
_stats = {"total_refunded_cents": 0, "refund_count": 0}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/ledger":
            with _lock:
                self._json(200, {
                    "orders": dict(_orders),
                    "total_refunded_usd": f"{_stats['total_refunded_cents'] / 100:.2f}",
                    "refund_count": _stats["refund_count"],
                })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_body()
        if self.path == "/order":
            self._handle_order(body)
        elif self.path == "/refund":
            self._handle_refund(body)
        elif self.path == "/reset":
            self._handle_reset(body)
        else:
            self._json(404, {"error": "not found"})

    def _handle_order(self, body):
        order_id = body.get("order_id", "")
        amount_cents = body.get("amount_cents", 0)
        if not order_id or not amount_cents:
            self._json(400, {"error": "order_id and amount_cents required"})
            return
        with _lock:
            _orders[order_id] = {
                "amount_cents": amount_cents,
                "refunded_cents": 0,
                "refunds": [],
            }
        self._json(201, {"status": "created", "order_id": order_id, "amount_cents": amount_cents})

    def _handle_refund(self, body):
        order_id = body.get("order_id", "")
        amount_cents = body.get("amount_cents", 0)
        if not order_id or not amount_cents:
            self._json(400, {"error": "order_id and amount_cents required"})
            return
        with _lock:
            order = _orders.get(order_id)
            if order is None:
                self._json(404, {"error": f"order {order_id} not found"})
                return
            # NON-IDEMPOTENT: always credits, even if it exceeds original
            refund_number = len(order["refunds"]) + 1
            order["refunded_cents"] += amount_cents
            order["refunds"].append({"amount_cents": amount_cents, "number": refund_number})
            _stats["total_refunded_cents"] += amount_cents
            _stats["refund_count"] += 1
        self._json(200, {
            "status": "refunded",
            "order_id": order_id,
            "amount_cents": amount_cents,
            "refund_number": refund_number,
            "total_refunded_cents": order["refunded_cents"],
        })

    def _handle_reset(self, body):
        order_id = body.get("order_id", "")
        with _lock:
            if order_id and order_id in _orders:
                del _orders[order_id]
            elif not order_id:
                _orders.clear()
            _stats["total_refunded_cents"] = 0
            _stats["refund_count"] = 0
        self._json(200, {"status": "reset"})

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
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
        pass  # silence request logs


if __name__ == "__main__":
    port = 8082
    print(f"refund-app listening on :{port}")
    HTTPServer(("", port), Handler).serve_forever()
