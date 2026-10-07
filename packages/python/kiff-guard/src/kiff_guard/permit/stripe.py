"""The reference adapter: Stripe refunds (RFC 046 D5).

``execute`` creates one refund with the operation id as Stripe's
``Idempotency-Key`` and as ``metadata[kiff_op]``. ``lookup`` lists the
payment's refunds and matches ``metadata[kiff_op]``; finding nothing does not
prove the refund did not happen, so the verifier leaves such a call
``unknown`` for a person.

Stripe saves the result of the first request that began executing for an
idempotency key, success or failure, and may prune keys after 24 hours
(https://docs.stripe.com/api/idempotent_requests). The verifier never
resends, so the key only guards against two requests for the same operation
reaching Stripe at all.

Only the standard library is used for HTTP. The key never leaves this
process; KIFF never sees it.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional

from .verifier import Adapter, Outcome

__all__ = ["StripeRefunds", "StripeError"]

API = "https://api.stripe.com/v1"


class StripeError(Exception):
    def __init__(self, status: int, body: Dict[str, Any]) -> None:
        err = body.get("error") or {}
        super().__init__(err.get("message") or "Stripe refused the request")
        self.status, self.body, self.type = status, body, err.get("type", "")


class StripeRefunds(Adapter):
    """Refund a payment, at most once per KIFF operation.

    ``resolve(arguments)`` maps the tool's arguments to the refund: a dict
    with ``payment_intent`` and ``amount`` (in the currency's smallest unit),
    and optionally ``metadata`` (a dict of strings) and ``reason``. It may
    read from Stripe (it is called again by ``lookup``) but must not write.
    """

    def __init__(self, api_key: str, resolve: Callable[[Dict[str, Any]], Dict[str, Any]], *,
                 api: str = API, timeout: float = 15, opener: Optional[Callable] = None) -> None:
        if not api_key:
            raise ValueError("a Stripe API key is required")
        self._key, self.resolve, self.api, self.timeout = api_key, resolve, api, timeout
        self._open = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, params: Dict[str, Any], idem: Optional[str] = None) -> Dict[str, Any]:
        q = urllib.parse.urlencode(params, doseq=True)
        url = self.api + path + ("?" + q if method == "GET" and q else "")
        req = urllib.request.Request(url, data=q.encode() if method == "POST" else None, method=method)
        req.add_header("Authorization", "Basic " + base64.b64encode((self._key + ":").encode()).decode())
        if idem:
            req.add_header("Idempotency-Key", idem[:255])
        try:
            with self._open(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            raise StripeError(e.code, body) from None

    def prepare(self, op: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Read-only: resolve the refund and build its parameters. A failure
        here sends nothing."""
        ref = self.resolve(arguments)
        params: Dict[str, Any] = {"payment_intent": ref["payment_intent"], "amount": int(ref["amount"]),
                                  "metadata[kiff_op]": op}
        for k, v in (ref.get("metadata") or {}).items():
            params["metadata[%s]" % k] = str(v)[:500]
        if ref.get("reason"):
            params["reason"] = ref["reason"]
        return params

    def execute(self, op: str, params: Dict[str, Any]) -> Outcome:
        """The one effectful request, made at once."""
        try:
            r = self._request("POST", "/refunds", params, idem=op)
        except StripeError as e:
            if e.status in (400, 402, 404) and e.type in ("invalid_request_error", "card_error"):
                # A final refusal: Stripe did not refund.
                return Outcome("failed", {"error": str(e)}, reason="stripe_refused")
            return Outcome("unknown", {"error": str(e)}, reason="stripe_%d" % e.status)
        except Exception as e:
            return Outcome("unknown", {"error": type(e).__name__}, reason="no_answer")
        return Outcome("succeeded", _refund(r))

    def lookup(self, op: str, arguments: Dict[str, Any]) -> Optional[Outcome]:
        ref = self.resolve(arguments)
        page = self._request("GET", "/refunds", {"payment_intent": ref["payment_intent"], "limit": 100})
        for r in page.get("data") or []:
            if (r.get("metadata") or {}).get("kiff_op") == op:
                return Outcome("succeeded", _refund(r))
        return None


def _refund(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": r.get("id"), "amount": r.get("amount"), "currency": r.get("currency"),
            "status": r.get("status"), "payment_intent": r.get("payment_intent")}
