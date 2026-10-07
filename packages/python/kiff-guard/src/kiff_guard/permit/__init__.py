"""Verify KIFF execution permits (RFC 046) in your own tool or relay, so
KIFF needs no key to the system the tool changes.

Install with ``pip install "kiff-guard[verifier]"`` (adds ``cryptography``
for Ed25519). See :mod:`kiff_guard.permit.verifier` for the checks and the
at-most-once contract, :mod:`kiff_guard.permit.stripe` for the reference
adapter, and :mod:`kiff_guard.permit.relay` to run the verifier as a relay.
"""

from .jcs import args_sha256, canonicalize
from .keys import DEFAULT_JWKS_URL, JWKSKeys, KeyUnavailable, PinnedKey, PinnedKeys
from .store import SQLiteStore
from .token import PermitError
from .verifier import Adapter, Outcome, Verifier

__all__ = [
    "Verifier",
    "Outcome",
    "Adapter",
    "PermitError",
    "JWKSKeys",
    "PinnedKeys",
    "PinnedKey",
    "KeyUnavailable",
    "DEFAULT_JWKS_URL",
    "SQLiteStore",
    "args_sha256",
    "canonicalize",
]

PERMIT_HEADER = "KIFF-Permit"
