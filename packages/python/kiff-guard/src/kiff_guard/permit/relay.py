"""A relay that holds the downstream key, so KIFF does not (RFC 046 D6).

For a service that cannot check KIFF's permit itself (Stripe, Zendesk), run
this next to your vault. KIFF's gateway connects to it in ``relay`` mode and
sends each allowed call with its execution permit. The relay verifies the
permit, makes the one downstream call it is configured for with the key from
your environment or vault, and returns the result.

It is configured with an explicit list of tools, each mapped to one adapter.
It is not a network proxy: a tool that is not listed does not exist.

KIFF authenticates to the relay with a transport credential (a bearer here;
mTLS in front of it is recommended). KIFF holds that credential, and on its
own it executes nothing: every call also needs a valid permit.

It is a WSGI app, so any WSGI server can run it::

    app = Relay(verifier, {"refund_order": RelayTool(adapter, input_schema, "Refund an order")},
                transport_token=os.environ["RELAY_TOKEN"])
    wsgiref.simple_server.make_server("127.0.0.1", 8787, app).serve_forever()
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Dict, Iterable, Optional

from . import PERMIT_HEADER
from .verifier import Adapter, Outcome, Verifier

__all__ = ["Relay", "RelayTool", "mcp_result"]

PROTOCOL = "2025-11-25"


class RelayTool:
    def __init__(self, adapter: Adapter, input_schema: Dict[str, Any], description: str = "",
                 read_only: bool = False) -> None:
        self.adapter, self.input_schema, self.description, self.read_only = adapter, input_schema, description, read_only


def mcp_result(outcome: Outcome) -> Dict[str, Any]:
    """An MCP tools/call result for an Outcome. Anything but a success is an
    error result whose text says what happened, so the agent is told."""
    texts = {
        "succeeded": "Done.",
        "failed": "The service refused the call.",
        "not_sent": "Not sent: " + (outcome.message or outcome.reason),
        "unknown": "This call may have run; it will not be sent again. Check the service before retrying with a new operation.",
        "in_progress": "This call is already running; retry the same call shortly.",
        "refused": "Refused: " + (outcome.message or outcome.reason),
    }
    text = texts.get(outcome.state, outcome.state)
    if outcome.result is not None:
        text += " " + json.dumps(outcome.result, sort_keys=True)
    return {"content": [{"type": "text", "text": text}], "isError": outcome.state != "succeeded",
            "structuredContent": {"state": outcome.state, "reason": outcome.reason, "result": outcome.result}}


class Relay:
    def __init__(self, verifier: Verifier, tools: Dict[str, RelayTool], *, transport_token: str = "",
                 name: str = "kiff-relay") -> None:
        self.verifier, self.tools, self.name = verifier, dict(tools), name
        self._token = transport_token

    def _authorized(self, header: str) -> bool:
        if not self._token:
            return True
        return hmac.compare_digest(header.encode(), ("Bearer " + self._token).encode())

    def handle(self, msg: Dict[str, Any], permit: str) -> Optional[Dict[str, Any]]:
        """One JSON-RPC message; None for a notification."""
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            return None
        if method == "initialize":
            result: Any = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                           "serverInfo": {"name": self.name, "version": "1"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": t.description, "inputSchema": t.input_schema,
                                 "annotations": {"readOnlyHint": t.read_only}} for n, t in self.tools.items()]}
        elif method == "tools/call":
            p = msg.get("params") or {}
            tool = self.tools.get(p.get("name"))
            args = p.get("arguments")
            if tool is None or not isinstance(args, dict):
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool or arguments"}}
            if not permit:
                result = mcp_result(Outcome("refused", reason="no_permit", message="no KIFF execution permit was sent"))
            else:
                result = mcp_result(self.verifier.run(permit, p["name"], args, tool.adapter))
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def __call__(self, environ, start_response) -> Iterable[bytes]:
        def reply(status: str, body: bytes = b"", ctype: str = "application/json"):
            start_response(status, [("Content-Type", ctype), ("Content-Length", str(len(body)))])
            return [body]

        if environ.get("REQUEST_METHOD") != "POST":
            return reply("405 Method Not Allowed")
        if not self._authorized(environ.get("HTTP_AUTHORIZATION", "")):
            return reply("401 Unauthorized", b"unauthorized", "text/plain")
        try:
            n = int(environ.get("CONTENT_LENGTH") or 0)
            msg = json.loads(environ["wsgi.input"].read(min(n, 1 << 20)) or b"{}")
        except ValueError:
            return reply("400 Bad Request", b"invalid JSON", "text/plain")
        if not isinstance(msg, dict):
            return reply("400 Bad Request", b"expected one JSON-RPC message", "text/plain")
        if msg.get("method") == "server/discover":
            return reply("404 Not Found")  # not a 2026 server: the gateway falls back to initialize
        out = self.handle(msg, environ.get("HTTP_KIFF_PERMIT", ""))
        if out is None:
            return reply("202 Accepted")
        return reply("200 OK", json.dumps(out).encode())
