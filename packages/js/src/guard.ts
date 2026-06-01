/**
 * guard — the framework-agnostic core.
 *
 * `Guard` knows nothing about any agent framework. It exposes the
 * primitives adapters build on, depending on the framework's control
 * shape (1:1 port of the Python SDK's guard.py):
 *
 *   observe(tool, args)           — learn + record an "observed" receipt.
 *                                   No decision, no run. (observe mode)
 *   decideOnly(tool, args)        — learn + call KIFF decide and return
 *                                   the Decision. Does NOT run the tool and
 *                                   does NOT record — the adapter records
 *                                   exactly one receipt via recordExecuted
 *                                   (allowed) or recordWithheld (withheld).
 *   recordExecuted / recordWithheld — the vote-shape adapter's single
 *                                   audit write, so one receipt per call.
 *   evaluate(tool, args, run)     — convenience for middleware frameworks
 *                                   that let the guard run the tool.
 *
 * OpenClaw's `before_tool_call` is a vote shape: OpenClaw runs the tool
 * itself; the hook returns a verdict. So its adapter uses observe() /
 * decideOnly() + recordExecuted/recordWithheld, never evaluate(run).
 *
 * observe mode is decide-independent (#244): it works with no client and
 * no tenant, so a fresh user gets a real audit trail before they have any
 * KIFF account. The guard logic lives here, once; adapters add none.
 */

import { Catalog } from "./catalog.js";
import type { Client } from "./client.js";
import { Decision, Hold, type Receipt } from "./decision.js";

export type GuardMode = "observe" | "enforce";

export interface GuardOptions {
  client?: Client;
  tenant?: string;
  agent?: string;
  mode?: GuardMode;
  /** share a Catalog across guards on one tenant for one learned surface. */
  catalog?: Catalog;
  /** share a ledger across guards for one audit log over every agent. */
  ledger?: Receipt[];
}

export class Guard {
  readonly client?: Client;
  readonly tenant: string;
  readonly agent: string;
  readonly mode: GuardMode;
  readonly catalog: Catalog;
  readonly receipts: Receipt[];

  constructor(opts: GuardOptions = {}) {
    const mode = opts.mode ?? "observe";
    if (mode !== "observe" && mode !== "enforce") {
      throw new Error("mode must be 'observe' or 'enforce'");
    }
    // enforce calls decide -> needs a client. observe is decide-
    // independent and works with no client at all (#244).
    if (mode === "enforce" && !opts.client) {
      throw new Error("enforce mode requires a client");
    }
    this.client = opts.client;
    this.tenant = opts.tenant ?? "";
    this.agent = opts.agent ?? "agent";
    this.mode = mode;
    this.catalog = opts.catalog ?? new Catalog();
    this.receipts = opts.ledger ?? [];
  }

  /**
   * Record an observed receipt and learn the catalog. No decision, no
   * run. Decide-independent (#244): never calls KIFF. Valid with no
   * client and no tenant.
   */
  observe(tool: string, args: Record<string, unknown>): void {
    this.catalog.record(this.agent, tool, args);
    this.recordObserved(tool, args);
  }

  /**
   * Ask KIFF to decide and return the Decision WITHOUT running the tool
   * and WITHOUT recording a receipt. The primitive for vote-shape
   * adapters in enforce mode: the framework runs or skips the tool based
   * on `decision.withheld`, then the adapter records exactly one receipt
   * via recordExecuted (allowed) or recordWithheld (withheld).
   *
   * Why no receipt here: the decision and the execution are two moments
   * for a vote-shape adapter, but the *audit* must be one row per tool
   * call. So recording is the adapter's explicit, single call, never a
   * side effect of deciding. (The one-receipt rule, #239/#250.)
   */
  async decideOnly(tool: string, args: Record<string, unknown>): Promise<Decision> {
    if (!this.client) {
      throw new Error("decideOnly requires a client (enforce mode)");
    }
    this.catalog.record(this.agent, tool, args);
    return this.client.decide(this.tenant, this.agent, tool, args);
  }

  /**
   * Convenience entry point for middleware frameworks that let the guard
   * run the tool. `run` executes the tool. Returns the tool result, or
   * throws Hold in enforce mode when KIFF withholds clearance.
   */
  async evaluate<T>(tool: string, args: Record<string, unknown>, run: () => T | Promise<T>): Promise<T> {
    // Learn from every call, in both modes — integration is discovery.
    this.catalog.record(this.agent, tool, args);

    if (this.mode === "observe") {
      const result = await run();
      this.recordObserved(tool, args);
      return result;
    }

    const decision = await this.client!.decide(this.tenant, this.agent, tool, args);
    if (decision.allowed) {
      const result = await run();
      this.recordGoverned(tool, args, decision, true);
      return result;
    }
    this.recordGoverned(tool, args, decision, false);
    throw new Hold(decision);
  }

  /**
   * Record exactly one governed receipt for an action the framework
   * executed after an allowed decideOnly. The vote-shape adapter's single
   * audit write on the allowed path.
   */
  recordExecuted(tool: string, args: Record<string, unknown>, decision: Decision): void {
    this.recordGoverned(tool, args, decision, true);
  }

  /**
   * Record exactly one governed receipt for an action KIFF withheld (the
   * framework skipped it). Pairs with recordExecuted so a vote-shape
   * adapter emits one receipt per call, matching the middleware path.
   */
  recordWithheld(tool: string, args: Record<string, unknown>, decision: Decision): void {
    this.recordGoverned(tool, args, decision, false);
  }

  // --- audit ---------------------------------------------------------

  private recordObserved(tool: string, args: Record<string, unknown>): void {
    this.receipts.push({
      ts: Date.now() / 1000,
      agent: this.agent,
      tool,
      args: { ...args },
      outcome: "observed",
      reason: "observe mode: recorded, not governed",
      executed: true,
      state: "observed",
    });
  }

  private recordGoverned(
    tool: string,
    args: Record<string, unknown>,
    decision: Decision,
    executed: boolean,
  ): void {
    this.receipts.push({
      ts: Date.now() / 1000,
      agent: this.agent,
      tool,
      args: { ...args },
      outcome: decision.outcome,
      reason: decision.reason,
      executed,
      state: "governed",
      proposalId: decision.proposalId,
    });
  }
}
