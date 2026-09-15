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
import type { Client, GuardConnection, GuardConnector } from "./client.js";
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
  /**
   * Identifier for the agent run these calls belong to, sent as run
   * context so decisions within one run can be correlated (kiff-cloud
   * RFC 039).
   */
  runId?: string;
  /**
   * Tools whose *results* bring content from somewhere the agent's
   * instructions do not come from: a fetched page, a third-party ticket,
   * a document, a tool reaching outside this run's remit.
   *
   * The integrator declares the set up front; the guard applies it
   * mechanically by tool name. The model can choose to call such a tool,
   * and calling it can only ever ADD taint, never remove it.
   */
  untrustedTools?: Iterable<string>;
}

export interface GuardConnectOptions {
  /**
   * Adapter/runtime name, e.g. "openclaw". Required so Cloud can group
   * live agents by integration surface without inspecting tool traffic.
   */
  adapter: string;
  project?: string;
  environment?: string;
  workflow?: string;
  sdkVersion?: string;
}

export class Guard {
  readonly client?: Client;
  readonly tenant: string;
  readonly agent: string;
  readonly mode: GuardMode;
  readonly catalog: Catalog;
  readonly receipts: Receipt[];
  /** @see GuardOptions.untrustedTools */
  readonly untrustedTools: ReadonlySet<string>;
  private runId: string;
  private untrustedInputSeen = false;
  private runContextOn: boolean;

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
    // Run context (kiff-cloud RFC 039). Asserted by this guard — which is
    // trusted integrator code — and never by the model.
    this.runId = opts.runId ?? "";
    this.untrustedTools = new Set(opts.untrustedTools ?? []);
    // Opt-in, and off until the integrator asks for it. A guard that
    // never opts in sends no run_context and calls Client.decide with its
    // original signature, so every Client written before RFC 039 —
    // including custom ones outside this repo — keeps working.
    //
    // Opting out is not a way to dodge the control: an action that
    // declares a run-context dependency and receives no assertion fails
    // closed cloud-side. Sending nothing means "I have not established
    // anything", never "this run is clean".
    this.runContextOn = this.runId !== "" || this.untrustedTools.size > 0;
  }

  /**
   * Assert that content from an untrusted source has entered this run.
   * Monotonic: once asserted it holds until startRun().
   *
   * Call it where the untrusted content actually arrives.
   * `untrustedTools` does this automatically for tools named up front;
   * this is the manual path for everything else (a webhook body, a
   * user-pasted document, a file read outside the tool layer).
   */
  markUntrustedInput(source = ""): void {
    this.untrustedInputSeen = true;
    this.runContextOn = true;
    if (source) {
      this.catalog.record(this.agent, `kiff.untrusted_input:${source}`, {});
    }
  }

  /**
   * Begin a new run: clears the untrusted-input assertion and sets the
   * run id. It is an integrator action by construction — the model has no
   * route to it — which is what makes clearing taint here safe and
   * clearing it anywhere else not. There is deliberately no untaint().
   */
  startRun(runId = ""): void {
    this.runId = runId;
    this.untrustedInputSeen = false;
    this.runContextOn = true;
  }

  /** Whether this run has been marked as having consumed untrusted input. */
  get untrustedInput(): boolean {
    return this.untrustedInputSeen;
  }

  /**
   * The run context to send with a decision, or undefined when this guard
   * never opted in.
   *
   * Always includes `untrusted_input`, including when false: an explicit
   * clean assertion and no assertion at all are different facts to the
   * runtime, and a declaring action fails closed on the second. A guard
   * that sends this is making the first claim and is responsible for it
   * being true.
   */
  runContext(): Record<string, unknown> | undefined {
    if (!this.runContextOn) return undefined;
    const ctx: Record<string, unknown> = { untrusted_input: this.untrustedInputSeen };
    if (this.runId) ctx.run_id = this.runId;
    return ctx;
  }

  /**
   * Apply the declared untrusted-tool set. Called after a tool has run,
   * so the taint lands on everything the agent does *next* — the causal
   * order that matters. Reading a public issue is not itself the problem;
   * what the agent does afterwards is.
   */
  private noteUntrustedTool(tool: string): void {
    if (this.untrustedTools.has(tool)) {
      this.untrustedInputSeen = true;
    }
  }

  /**
   * Call the client, passing run context only when this guard has any.
   * Keeps the Client contract unchanged for callers that never opted in.
   */
  private async decideWithContext(tool: string, args: Record<string, unknown>): Promise<Decision> {
    const ctx = this.runContext();
    if (ctx === undefined) {
      return this.client!.decide(this.tenant, this.agent, tool, args);
    }
    return this.client!.decide(this.tenant, this.agent, tool, args, ctx);
  }

  /**
   * Record an observed receipt and learn the catalog. No decision, no
   * run. Decide-independent (#244): never calls KIFF. Valid with no
   * client and no tenant.
   */
  observe(tool: string, args: Record<string, unknown>): void {
    this.catalog.record(this.agent, tool, args);
    this.recordObserved(tool, args);
    this.noteUntrustedTool(tool);
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
    return this.decideWithContext(tool, args);
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
      this.noteUntrustedTool(tool);
      return result;
    }

    const decision = await this.decideWithContext(tool, args);
    if (decision.allowed) {
      const result = await run();
      this.recordGoverned(tool, args, decision, true);
      this.noteUntrustedTool(tool);
      return result;
    }
    this.recordGoverned(tool, args, decision, false);
    throw new Hold(decision);
  }

  /**
   * Opt into KIFF Cloud runtime discovery. This is separate from observe
   * and enforce so zero-config audit stays local unless the caller
   * provides a Cloud-capable client and calls connect().
   */
  async connect(opts: GuardConnectOptions): Promise<GuardConnection> {
    if (!isGuardConnector(this.client)) {
      throw new Error("connect requires a client with connectGuard");
    }
    return this.client.connectGuard({
      agentId: this.agent,
      adapter: opts.adapter,
      mode: this.mode,
      project: opts.project,
      environment: opts.environment,
      workflow: opts.workflow,
      sdkVersion: opts.sdkVersion,
    });
  }

  /**
   * Record exactly one governed receipt for an action the framework
   * executed after an allowed decideOnly. The vote-shape adapter's single
   * audit write on the allowed path.
   */
  recordExecuted(tool: string, args: Record<string, unknown>, decision: Decision): void {
    this.recordGoverned(tool, args, decision, true);
    // Vote shape runs the tool outside the guard, so this is the only
    // point where the guard learns it actually ran. Without it, a
    // vote-shape adapter would never taint and every declared untrusted
    // tool would be invisible to run context — in exactly the adapters
    // most likely to be reading third-party content.
    this.noteUntrustedTool(tool);
  }

  /**
   * Record exactly one governed receipt for an action KIFF withheld (the
   * framework skipped it). Pairs with recordExecuted so a vote-shape
   * adapter emits one receipt per call, matching the middleware path.
   */
  recordWithheld(tool: string, args: Record<string, unknown>, decision: Decision): void {
    this.recordGoverned(tool, args, decision, false);
  }

  /**
   * Record a receipt for an action handed to a human reviewer through the
   * host framework's own approval flow.
   *
   * Distinct from recordWithheld because the terminal outcome is not
   * observable at this seam: the framework pauses, the human answers, and if
   * they approve the tool runs without calling back into the guard. Recording
   * `executed: false` there would assert that the side effect did not happen,
   * when it may well have. This records what is actually known — the call was
   * governed and routed to a human — and leaves `executed` unset.
   */
  recordPendingApproval(tool: string, args: Record<string, unknown>, decision: Decision): void {
    this.receipts.push({
      ts: Date.now() / 1000,
      agent: this.agent,
      tool,
      args: { ...args },
      outcome: decision.outcome,
      reason: decision.reason,
      state: "governed",
      proposalId: decision.proposalId,
    });
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

function isGuardConnector(client: Client | undefined): client is Client & GuardConnector {
  return !!client && typeof (client as Partial<GuardConnector>).connectGuard === "function";
}
