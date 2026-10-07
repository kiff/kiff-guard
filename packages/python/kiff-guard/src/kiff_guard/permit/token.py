"""Parsing and checking a KIFF execution permit's signature and claims.

A permit is a compact JWS (RFC 7515) with header ``alg: Ed25519`` (RFC 9864;
``EdDSA`` and every other value are refused), ``typ: kiff-permit+jwt`` and a
``kid``. The signature is checked with the ``cryptography`` package's
Ed25519, not a JOSE library, so no algorithm is ever negotiated.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Tuple

__all__ = ["PermitError", "TYPE", "ALG", "DETAIL_TYPE", "decode_and_verify"]

TYPE = "kiff-permit+jwt"
ALG = "Ed25519"
DETAIL_TYPE = "https://kiff.dev/permits/tool-call"


class PermitError(Exception):
    """The permit does not authorize this call. ``code`` is stable and
    machine-readable; the message says why for a person."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _b64url(s: str) -> bytes:
    if not isinstance(s, str) or any(c in s for c in "+/="):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _ed25519_verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:  # pragma: no cover - depends on the install
        raise ImportError('verifying KIFF permits needs the verifier extra: pip install "kiff-guard[verifier]"') from e
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except InvalidSignature:
        return False


def decode_and_verify(token: str, key_for_kid) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Check the header and signature and return (header, claims).
    ``key_for_kid(kid)`` returns the trusted public key or None."""
    if not isinstance(token, str) or token.count(".") != 2 or len(token) > 8192:
        raise PermitError("malformed", "the permit is not a compact JWS")
    h64, p64, s64 = token.split(".")
    try:
        header = json.loads(_b64url(h64))
        claims = json.loads(_b64url(p64))
        sig = _b64url(s64)
    except Exception:
        raise PermitError("malformed", "the permit is not a compact JWS") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise PermitError("malformed", "the permit's header and claims must be JSON objects")
    if header.get("typ") != TYPE:
        raise PermitError("wrong_type", "the token is not a KIFF execution permit (typ)")
    if header.get("alg") != ALG:
        raise PermitError("wrong_alg", "the permit must be signed with Ed25519 (alg)")
    if "crit" in header:
        raise PermitError("malformed", "the permit names critical header parameters this verifier does not know")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise PermitError("unknown_key", "the permit names no signing key")
    pub = key_for_kid(kid)
    if pub is None:
        raise PermitError("unknown_key", "the permit's signing key is not trusted: " + kid)
    if len(sig) != 64 or not _ed25519_verify(pub, sig, (h64 + "." + p64).encode("ascii")):
        raise PermitError("bad_signature", "the permit's signature does not verify")
    return header, claims
