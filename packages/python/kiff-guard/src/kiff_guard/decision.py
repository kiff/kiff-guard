"""Core value types shared across the guard.

These are the framework-agnostic vocabulary. No framework, no transport,
no I/O — just the shapes the guard reasons about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


# The stable outcome vocabulary the KIFF decide endpoint returns.
# "observed" is guard-local: it
# is what observe mode records when no decision was made.
ALLOWED = "allowed"
APPROVAL_REQUIRED = "approval_required"
BLOCKED = "blocked"
INVALID = "invalid"
LIMIT_EXCEEDED = "limit_exceeded"
OBSERVED = "observed"

# Outcomes that mean "do not run the tool" in enforce mode. Kept as the
# known set for readability/telemetry, but `withheld` below is defined as
# the *negation of allowed*, so an UNKNOWN future outcome (e.g. a new
# "quarantined" / "rate_limited" the cloud adds later) fails SAFE — it
# withholds rather than running an ungoverned tool. See RFC 017 (E4).
WITHHELD = (APPROVAL_REQUIRED, BLOCKED, INVALID, LIMIT_EXCEEDED)


@dataclass
class Decision:
    """What KIFF cleared (or would have). `proposal_id` is the runtime's
    id for the proposal — used to resolve an approval and to correlate the
    audit trail. Never a client-side hash."""

    outcome: str
    reason: str = ""
    proposal_id: str = ""

    @property
    def allowed(self) -> bool:
        return self.outcome == ALLOWED

    @property
    def withheld(self) -> bool:
        # Fail-safe: anything that is not an explicit allow withholds.
        # Defined as `not allowed` (rather than membership in WITHHELD) so
        # an outcome the SDK has never heard of still blocks the tool —
        # the cloud can add new outcomes without old SDKs failing open.
        # OBSERVED is guard-local and never reaches an enforce decision.
        return self.outcome != ALLOWED


@dataclass
class Receipt:
    """One line of the audit trail.

    `state` is the honesty field (#244):
      - "observed" — observe mode; NO decide call was made; outcome is
        "observed". A real record of what the agent did, not a governance
        verdict.
      - "governed"  — enforce mode; KIFF decide WAS called; outcome is its
        real verdict and `executed` reflects whether the tool ran.
    """

    ts: float
    agent: str
    tool: str
    args: Dict[str, Any]
    outcome: str
    reason: str
    executed: bool
    state: str
    proposal_id: str = ""


class Hold(Exception):
    """Raised in enforce mode when KIFF withholds clearance. Carries the
    Decision so the application can route the hold to a human
    (approval_required) or surface the refusal (blocked / invalid /
    limit_exceeded). Maps onto each framework's native HITL / interrupt."""

    def __init__(self, decision: Decision):
        self.decision = decision
        super().__init__(f"{decision.outcome}: {decision.reason}")
