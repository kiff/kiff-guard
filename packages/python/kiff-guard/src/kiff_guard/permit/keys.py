"""Which permit-signing keys a verifier trusts, and for how long (RFC 046 D4).

Trust comes from the latest key set fetched, not from having once seen a key:

- :class:`JWKSKeys` refetches KIFF's JWKS at least every ``refresh`` seconds
  (5 minutes), and on an unknown ``kid`` at most once a minute. A key absent
  from the latest successful fetch is no longer trusted. If fetching fails,
  the last good set stays trusted for at most ``stale_limit`` seconds (1 hour)
  from its fetch, then the verifier fails closed.
- :class:`PinnedKeys` is a fixed set for offline or locked-down deployments.
  Each key carries a ``not_after``; past it the key is refused, so a
  forgotten pin fails closed instead of trusting a key forever.
- Both take a ``distrust`` list of key ids refused whatever the key set says:
  the customer's own emergency switch, and the only one that works offline.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.request
from typing import Callable, Dict, Iterable, Optional

__all__ = ["KeyUnavailable", "JWKSKeys", "PinnedKeys", "PinnedKey", "DEFAULT_JWKS_URL"]

DEFAULT_JWKS_URL = "https://api.kiff.dev/.well-known/kiff-permit-keys.json"


class KeyUnavailable(Exception):
    """The key set cannot be trusted right now (fetch failing past the stale
    limit). The call is refused; it is safe to retry later."""


def _b64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def parse_jwks(doc: dict) -> Dict[str, bytes]:
    """The Ed25519 public keys of a JWKS, by kid. Other key types are
    ignored: a permit is only ever signed with Ed25519."""
    out: Dict[str, bytes] = {}
    for k in doc.get("keys") or []:
        if not isinstance(k, dict):
            continue
        if k.get("kty") != "OKP" or k.get("crv") != "Ed25519" or k.get("alg", "Ed25519") != "Ed25519":
            continue
        kid, x = k.get("kid"), k.get("x")
        if not isinstance(kid, str) or not isinstance(x, str):
            continue
        try:
            pub = _b64url(x)
        except Exception:
            continue
        if len(pub) == 32:
            out[kid] = pub
    return out


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/jwk-set+json, application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - fixed https URL by default
        return json.loads(r.read(256 * 1024))


class JWKSKeys:
    """KIFF's published keys, refetched on a bound (see the module doc)."""

    def __init__(
        self,
        url: str = DEFAULT_JWKS_URL,
        *,
        refresh: float = 300,
        unknown_kid_interval: float = 60,
        stale_limit: float = 3600,
        distrust: Iterable[str] = (),
        fetch: Optional[Callable[[str], dict]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if refresh > 300:
            raise ValueError("refresh must be at most 300 seconds (RFC 046 D4)")
        if stale_limit > 3600:
            raise ValueError("stale_limit must be at most 3600 seconds (RFC 046 D4)")
        self.url = url
        self.refresh = refresh
        self.unknown_kid_interval = unknown_kid_interval
        self.stale_limit = stale_limit
        self.distrust = frozenset(distrust)
        self._fetch = fetch or _fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: Dict[str, bytes] = {}
        self._fetched_at: Optional[float] = None
        self._last_attempt = float("-inf")

    def _try_fetch(self, now: float) -> None:
        self._last_attempt = now
        try:
            keys = parse_jwks(self._fetch(self.url))
        except Exception:
            return  # keep the last good set; staleness is checked by the caller
        self._keys, self._fetched_at = keys, now

    def key(self, kid: str) -> Optional[bytes]:
        """The public key for kid, or None when it is not trusted. Raises
        KeyUnavailable when no key set may be trusted at all."""
        if kid in self.distrust:
            return None
        with self._lock:
            now = self._clock()
            if self._fetched_at is None or now - self._fetched_at >= self.refresh:
                if now - self._last_attempt >= min(self.unknown_kid_interval, self.refresh) or self._fetched_at is None:
                    self._try_fetch(now)
            elif kid not in self._keys and now - self._last_attempt >= self.unknown_kid_interval:
                self._try_fetch(now)
            if self._fetched_at is None or now - self._fetched_at > self.stale_limit:
                raise KeyUnavailable("KIFF's permit keys could not be fetched recently enough to trust")
            return self._keys.get(kid)


class PinnedKey:
    """One pinned key: its id, its 32-byte Ed25519 public key (raw bytes or
    base64url), and the Unix time after which it is refused."""

    def __init__(self, kid: str, public_key, not_after: float) -> None:
        self.kid = kid
        self.public_key = _b64url(public_key) if isinstance(public_key, str) else bytes(public_key)
        if len(self.public_key) != 32:
            raise ValueError("an Ed25519 public key is 32 bytes")
        self.not_after = float(not_after)


class PinnedKeys:
    """A fixed key set for offline verification (see the module doc). The
    residual risk: a compromised pinned key is accepted until it is added to
    ``distrust`` or reaches its ``not_after``."""

    def __init__(self, keys: Iterable[PinnedKey], *, distrust: Iterable[str] = (),
                 clock: Callable[[], float] = time.time) -> None:
        self._keys = {k.kid: k for k in keys}
        self.distrust = frozenset(distrust)
        self._clock = clock

    def key(self, kid: str) -> Optional[bytes]:
        if kid in self.distrust:
            return None
        k = self._keys.get(kid)
        if k is None or self._clock() > k.not_after:
            return None
        return k.public_key
