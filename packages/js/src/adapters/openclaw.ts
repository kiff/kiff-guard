/**
 * OpenClaw adapter — before_tool_call plugin hook (vote shape).
 *
 * Verified against the OpenClaw plugin SDK (docs/integration/frameworks/
 * openclaw.md, checked against openclaw/openclaw source):
 *
 *   - The seam is the `before_tool_call` typed plugin hook
 *     (`api.on("before_tool_call", handler, { priority })`). OpenClaw
 *     runs the tool itself; the hook only votes via its return value.
 *   - `event.toolName` + `event.params` carry the call.
 *   - Return nothing / undefined  -> the tool proceeds (allow).
 *   - Return `{ block: true, blockReason }` -> terminal; the tool is
 *     skipped and the model sees the reason.
 *   - Return `{ requireApproval: {...} }` -> OpenClaw pauses the run and
 *     routes a real human approval (the `/approve` flow). This is the
 *     first adapter where KIFF's `approval_required` renders as native
 *     human-in-the-loop rather than collapsing to a block.
 *
 * So OpenClaw is a VOTE shape (like Hermes / OpenAI Agents / ADK): the
 * adapter uses the guard's observe() / decideOnly() primitives +
 * recordExecuted / recordWithheld — one governed receipt per call —
 * never evaluate(run).
 *
 * This module imports nothing from OpenClaw at runtime — it only matches
 * the hook signature and the BeforeToolCallResult shape, so importing
 * @kiffhq/kiff-guard never requires the openclaw package. The types below
 * mirror the verified plugin-SDK contract.
 */

import type { Guard } from "../guard.js";

/** The fields of OpenClaw's before_tool_call event the adapter reads. */
export interface BeforeToolCallEvent {
  toolName: string;
  params?: Record<string, unknown>;
  runId?: string;
  toolCallId?: string;
}

/** OpenClaw's BeforeToolCallResult (the subset KIFF returns). */
export interface BeforeToolCallResult {
  block?: boolean;
  blockReason?: string;
  requireApproval?: {
    title: string;
    description: string;
    severity?: "info" | "warning" | "critical";
    timeoutMs?: number;
    timeoutBehavior?: "allow" | "deny";
    onResolution?: (d: "allow-once" | "allow-always" | "deny" | "timeout" | "cancelled") => void;
  };
}

export interface OpenClawHookOptions {
  /**
   * fail closed (enforce only, default true): if the guard errors (e.g.
   * transport failure to KIFF), block the tool. A governance layer must
   * not wave traffic through when its decision path is down. observe mode
   * always fails open — it never blocks anyway.
   */
  failClosed?: boolean;
  /**
   * approvalTimeoutMs for the requireApproval path (default 60_000).
   * timeoutBehavior is always "deny" — a timed-out approval fails closed.
   */
  approvalTimeoutMs?: number;
}

/**
 * Build a `before_tool_call` handler backed by the given Guard.
 *
 * observe mode: records + learns every call, never blocks (returns
 *   undefined so the tool proceeds).
 * enforce mode: calls KIFF; on `approval_required` returns a
 *   `requireApproval` directive (native human-in-the-loop); on any other
 *   withheld outcome returns `{ block: true }`; on allowed records that
 *   the tool ran and returns undefined.
 */
export function kiffBeforeToolCall(
  guard: Guard,
  opts: OpenClawHookOptions = {},
): (event: BeforeToolCallEvent) => Promise<BeforeToolCallResult | undefined> {
  const failClosed = opts.failClosed ?? true;
  const approvalTimeoutMs = opts.approvalTimeoutMs ?? 60_000;

  return async (event: BeforeToolCallEvent): Promise<BeforeToolCallResult | undefined> => {
    const tool = event.toolName ?? "";
    const args = (event.params && typeof event.params === "object" ? event.params : {}) as Record<string, unknown>;

    if (guard.mode === "observe") {
      try {
        guard.observe(tool, args);
      } catch {
        // observe never blocks; swallow audit/learn errors.
      }
      return undefined; // proceed
    }

    // enforce
    let decision;
    try {
      decision = await guard.decideOnly(tool, args);
    } catch (err) {
      if (failClosed) {
        const reason = err instanceof Error ? err.message : String(err);
        return { block: true, blockReason: `KIFF guard unavailable; blocking ${tool} (fail-closed): ${reason}` };
      }
      return undefined; // fail open (not recommended)
    }

    if (decision.allowed) {
      // OpenClaw will run the tool next. Record that it ran.
      guard.recordExecuted(tool, args, decision);
      return undefined; // proceed
    }

    // Withheld. Record exactly one governed receipt either way.
    guard.recordWithheld(tool, args, decision);

    if (decision.outcome === "approval_required") {
      // Native human-in-the-loop: OpenClaw pauses and routes to /approve.
      return {
        requireApproval: {
          title: `Approve ${tool}`,
          description: decision.reason || `KIFF requires approval for ${tool}`,
          severity: "warning",
          timeoutMs: approvalTimeoutMs,
          timeoutBehavior: "deny", // fail closed on timeout
        },
      };
    }

    // blocked / invalid / limit_exceeded / any unknown outcome -> block.
    return { block: true, blockReason: `KIFF withheld ${tool}: ${decision.outcome} — ${decision.reason}` };
  };
}

/** Minimal shape of the OpenClaw plugin `api` the registrar needs. */
export interface OpenClawPluginApi {
  on(
    hook: "before_tool_call",
    handler: (event: BeforeToolCallEvent) => Promise<BeforeToolCallResult | undefined>,
    opts?: { priority?: number },
  ): void;
}

/**
 * Register the KIFF guard on an OpenClaw plugin `api`. Call from your
 * plugin's `register(api)`:
 *
 *     import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
 *     import { Guard } from "@kiffhq/kiff-guard";
 *     import { registerKiffGuard } from "@kiffhq/kiff-guard/adapters/openclaw";
 *
 *     const guard = new Guard({ mode: "observe" });
 *     export default definePluginEntry({
 *       id: "kiff-guard",
 *       name: "KIFF Guard",
 *       register(api) { registerKiffGuard(api, guard); },
 *     });
 */
export function registerKiffGuard(
  api: OpenClawPluginApi,
  guard: Guard,
  opts: OpenClawHookOptions & { priority?: number } = {},
): void {
  const { priority = 50, ...hookOpts } = opts;
  api.on("before_tool_call", kiffBeforeToolCall(guard, hookOpts), { priority });
}
