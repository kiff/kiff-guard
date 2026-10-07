"""The verifier's durable record of each operation (RFC 046 D5).

One row per ``op``: the arguments hash, the arguments (for recovery lookups),
a state, the time of the first attempt, a lease, and the recorded result.
SQLite for the reference; a production deployment can implement the same
methods on its own database. Every state change is one transaction, so a
crash leaves either the previous state or the next one.

States: ``started`` (claimed; perhaps sent, perhaps not), ``succeeded`` and
``failed`` (final answers from the downstream service), ``not_sent`` (the
verifier refused to send it, for example because the permit expired before
the send), and ``unknown`` (the outcome could not be settled; shown to a
person, never resent).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, List, Optional

__all__ = ["Row", "SQLiteStore", "FINAL_STATES"]

FINAL_STATES = ("succeeded", "failed", "not_sent")


class Row:
    def __init__(self, op: str, tool: str, args_sha256: str, arguments: Any, state: str,
                 first_attempt_at: float, lease_owner: str, lease_until: float, result: Any, reason: str) -> None:
        self.op, self.tool, self.args_sha256, self.arguments = op, tool, args_sha256, arguments
        self.state, self.first_attempt_at = state, first_attempt_at
        self.lease_owner, self.lease_until = lease_owner, lease_until
        self.result, self.reason = result, reason


class SQLiteStore:
    """Durable operation records in a SQLite file (WAL, synchronous=FULL)."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=30)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS kiff_permit_ops (
                    op               TEXT PRIMARY KEY,
                    tool             TEXT NOT NULL,
                    args_sha256      TEXT NOT NULL,
                    arguments        TEXT NOT NULL,
                    state            TEXT NOT NULL,
                    first_attempt_at REAL NOT NULL,
                    lease_owner      TEXT NOT NULL DEFAULT '',
                    lease_until      REAL NOT NULL DEFAULT 0,
                    result           TEXT,
                    reason           TEXT NOT NULL DEFAULT '',
                    updated_at       REAL NOT NULL
                )""")

    _COLS = "op, tool, args_sha256, arguments, state, first_attempt_at, lease_owner, lease_until, result, reason"

    def _row(self, r) -> Row:
        return Row(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5], r[6], r[7],
                   json.loads(r[8]) if r[8] is not None else None, r[9])

    def get(self, op: str) -> Optional[Row]:
        with self._lock:
            r = self._db.execute("SELECT " + self._COLS + " FROM kiff_permit_ops WHERE op = ?", (op,)).fetchone()
        return self._row(r) if r else None

    def claim(self, op: str, tool: str, args_sha256: str, arguments: Any, owner: str, now: float, lease: float) -> bool:
        """Insert op as started with a lease, if no row exists. True when this
        caller now holds it; False when the op was already recorded."""
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO kiff_permit_ops (op, tool, args_sha256, arguments, state, first_attempt_at,"
                " lease_owner, lease_until, updated_at) VALUES (?, ?, ?, ?, 'started', ?, ?, ?, ?)",
                (op, tool, args_sha256, json.dumps(arguments), now, owner, now + lease, now))
            return cur.rowcount == 1

    def take_expired_lease(self, op: str, owner: str, now: float, lease: float) -> bool:
        """Take the lease of a started or unknown row whose lease has expired,
        for recovery. Only one caller wins."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE kiff_permit_ops SET lease_owner = ?, lease_until = ?, updated_at = ?"
                " WHERE op = ? AND state IN ('started', 'unknown') AND lease_until <= ?",
                (owner, now + lease, now, op, now))
            return cur.rowcount == 1

    def renew(self, op: str, owner: str, now: float, lease: float) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE kiff_permit_ops SET lease_until = ?, updated_at = ? WHERE op = ? AND lease_owner = ? AND state = 'started'",
                (now + lease, now, op, owner))
            return cur.rowcount == 1

    def finish(self, op: str, owner: str, state: str, result: Any, reason: str, now: float) -> bool:
        """Record the outcome, if this caller still holds the lease."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE kiff_permit_ops SET state = ?, result = ?, reason = ?, lease_until = 0, updated_at = ?"
                " WHERE op = ? AND lease_owner = ? AND state IN ('started', 'unknown')",
                (state, json.dumps(result) if result is not None else None, reason, now, op, owner))
            return cur.rowcount == 1

    def expired(self, now: float) -> List[Row]:
        """Rows in started whose lease has expired: the sweep's work."""
        with self._lock:
            rs = self._db.execute("SELECT " + self._COLS + " FROM kiff_permit_ops WHERE state = 'started' AND lease_until <= ?",
                                  (now,)).fetchall()
        return [self._row(r) for r in rs]

    def unknown(self) -> List[Row]:
        """Rows whose outcome is unknown, for a person to settle."""
        with self._lock:
            rs = self._db.execute("SELECT " + self._COLS + " FROM kiff_permit_ops WHERE state = 'unknown' ORDER BY first_attempt_at").fetchall()
        return [self._row(r) for r in rs]

    def close(self) -> None:
        with self._lock:
            self._db.close()
