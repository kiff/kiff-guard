"""RFC 8785 (JCS) canonical JSON, and the args_sha256 a permit carries.

KIFF hashes the arguments it forwards; the verifier hashes the arguments it
receives. Both must produce the same bytes, so this follows RFC 8785 exactly:
object members sorted by UTF-16 code units, no insignificant whitespace,
strings escaped as ECMAScript's JSON.stringify does, and numbers as IEEE 754
doubles in ECMAScript's shortest form. The test vectors are shared with
KIFF's own implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

__all__ = ["canonicalize", "args_sha256", "MAX_SAFE_INTEGER"]

#: The largest integer every JSON number maps to exactly (2**53 - 1).
#: RFC 8785 hashes numbers as IEEE 754 doubles, so two integers beyond it
#: can hash the same while the tool receives different values. They are
#: refused, here and in KIFF's issuer, so a hash names one value.
MAX_SAFE_INTEGER = 2**53 - 1


def args_sha256(arguments: Any) -> str:
    """Hex SHA-256 of the canonical form of ``arguments``."""
    return hashlib.sha256(canonicalize(arguments)).hexdigest()


def canonicalize(value: Any) -> bytes:
    """The RFC 8785 bytes of a parsed JSON value (dict, list, str, number,
    bool or None). Parse with ``json.loads``; do not pass a JSON string."""
    out: list = []
    _encode(value, out)
    return "".join(out).encode("utf-8")


def _encode(v: Any, out: list) -> None:
    if v is None:
        out.append("null")
    elif v is True:
        out.append("true")
    elif v is False:
        out.append("false")
    elif isinstance(v, int):
        if abs(v) > MAX_SAFE_INTEGER:
            raise ValueError("jcs: integer %d is beyond 2**53 - 1 and cannot be hashed without ambiguity" % v)
        out.append(_number(float(v)))
    elif isinstance(v, float):
        out.append(_number(v))
    elif isinstance(v, str):
        out.append(_string(v))
    elif isinstance(v, (list, tuple)):
        out.append("[")
        for i, e in enumerate(v):
            if i:
                out.append(",")
            _encode(e, out)
        out.append("]")
    elif isinstance(v, dict):
        for k in v:
            if not isinstance(k, str):
                raise TypeError("jcs: object keys must be strings")
        out.append("{")
        for i, k in enumerate(sorted(v, key=lambda s: s.encode("utf-16-be"))):
            if i:
                out.append(",")
            out.append(_string(k))
            out.append(":")
            _encode(v[k], out)
        out.append("}")
    else:
        raise TypeError("jcs: unsupported value %r" % type(v))


_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _string(s: str) -> str:
    parts = ['"']
    for ch in s:
        if ch in _SHORT:
            parts.append(_SHORT[ch])
        elif ord(ch) < 0x20:
            parts.append("\\u%04x" % ord(ch))
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def _number(f: float) -> str:
    if math.isnan(f) or math.isinf(f):
        raise ValueError("jcs: NaN and Infinity are not JSON numbers")
    if f == 0:
        return "0"
    sign = ""
    if f < 0:
        sign, f = "-", -f
    # repr gives the shortest round-trip digits; Decimal splits them.
    _, digits_t, exp = Decimal(repr(f)).as_tuple()
    digits = "".join(map(str, digits_t)).rstrip("0") or "0"
    # n: the position of the decimal point relative to the digits.
    n = len("".join(map(str, digits_t))) + exp
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    m = digits[0] + ("." + digits[1:] if k > 1 else "")
    return sign + m + "e" + ("+" if e >= 0 else "-") + str(abs(e))


def loads(raw: str) -> Any:
    """Parse JSON the way canonicalization expects (numbers as int/float)."""
    return json.loads(raw)
