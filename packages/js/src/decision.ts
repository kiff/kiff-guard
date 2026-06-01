/**
 * Core value types shared across the guard.
 *
 * The framework-agnostic vocabulary. No framework, no transport, no I/O —
 * just the shapes the guard reasons about. 1:1 port of the Python SDK's
 * decision.py.
 */

/**
 * The stable outcome vocabulary the KIFF decide endpoint returns. Mirrors
 * apps/api/internal/handlers/proposals.go. "observed" is guard-local: it
 * is what observe mode records when no decision was made.
 */
export const ALLOWED = "allowed";
export const APPROVAL_REQUIRED = "approval_required";
export const BLOCKED = "blocked";
export const INVALID = "invalid";
export const LIMIT_EXCEEDED = "limit_exceeded";
export const OBSERVED = "observed";

/**
 * Outcomes that mean "do not run the tool" in enforce mode. Kept as the
 * known set for readability/telemetry, but `withheld` below is defined as
 * the *negation of allowed*, so an UNKNOWN future outcome (e.g. a new
 * "quarantined" / "rate_limited" the cloud adds later) fails SAFE — it
 * withholds rather than running an ungoverned tool. See RFC 017 (E4).
 */
export const WITHHELD = [APPROVAL_REQUIRED, BLOCKED, INVALID, LIMIT_EXCEEDED] as const;

/**
 * What KIFF cleared (or would have). `proposalId` is the runtime's id for
 * the proposal — used to resolve an approval and to correlate the audit
 * trail. Never a client-side hash.
 */
export class Decision {
  readonly outcome: string;
  readonly reason: string;
  readonly proposalId: string;

  constructor(outcome: string, reason = "", proposalId = "") {
    this.outcome = outcome;
    this.reason = reason;
    this.proposalId = proposalId;
  }

  get allowed(): boolean {
    return this.outcome === ALLOWED;
  }

  /**
   * Fail-safe: anything that is not an explicit allow withholds. Defined
   * as `!allowed` (rather than membership in WITHHELD) so an outcome the
   * SDK has never heard of still blocks the tool — the cloud can add new
   * outcomes without old SDKs failing open. OBSERVED is guard-local and
   * never reaches an enforce decision.
   */
  get withheld(): boolean {
    return this.outcome !== ALLOWED;
  }
}

/**
 * One line of the audit trail.
 *
 * `state` is the honesty field (#244):
 *   - "observed" — observe mode; NO decide call was made; outcome is
 *     "observed". A real record of what the agent did, not a verdict.
 *   - "governed"  — enforce mode; KIFF decide WAS called; outcome is its
 *     real verdict and `executed` reflects whether the tool ran.
 */
export interface Receipt {
  ts: number;
  agent: string;
  tool: string;
  args: Record<string, unknown>;
  outcome: string;
  reason: string;
  executed: boolean;
  state: "observed" | "governed";
  proposalId?: string;
}

/**
 * Thrown in enforce mode when KIFF withholds clearance. Carries the
 * Decision so the application can route the hold to a human
 * (approval_required) or surface the refusal (blocked / invalid /
 * limit_exceeded). Maps onto each framework's native HITL / interrupt.
 */
export class Hold extends Error {
  readonly decision: Decision;
  constructor(decision: Decision) {
    super(`${decision.outcome}: ${decision.reason}`);
    this.name = "Hold";
    this.decision = decision;
  }
}
