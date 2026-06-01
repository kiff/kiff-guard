/**
 * client — the seam between the guard and KIFF.
 *
 * `HTTPClient` speaks the real KIFF decide protocol (RFC 017, /v1):
 *
 *     POST /v1/proposals/decide
 *     Authorization: Bearer kiff_live_<tenant>_<random>
 *     body: {entity_id, entity_type, action_name, actor_id, parameters,
 *            reasoning_summary?, confidence?, id?}
 *     -> {proposal_id, outcome, reasons[], message}
 *
 * `ToolMap` is the load-bearing bridge: an agent tool call gives a
 * function name + a flat args object, but decide needs action_name +
 * entity_id + entity_type. ToolMap binds each tool to its action and
 * names the arg that carries the entity id.
 *
 * Roles are deliberately NOT sent: the decide handler refuses caller-
 * asserted roles (a caller must not self-grant the authority that makes
 * its own action allowed). actor_id is sent; the API key's roles govern
 * server-side. The guard therefore cannot weaken the trust boundary.
 *
 * Uses the global `fetch` (Node >= 18) — zero required runtime deps.
 */

import { ALLOWED, Decision, INVALID } from "./decision.js";

/**
 * What the guard needs from a decider. Implemented by HTTPClient; tests
 * pass any object with this method. Async (unlike the Python sync client)
 * because JS HTTP is async and the OpenClaw hook is already async.
 */
export interface Client {
  decide(tenant: string, agent: string, tool: string, args: Record<string, unknown>): Promise<Decision>;
}

/** How one tool maps onto a KIFF action contract. */
export interface ToolBinding {
  /** the action_name the tenant's domain declares. */
  action: string;
  /** the entity_type the action operates on. */
  entityType: string;
  /** the tool argument carrying the entity id (read + excluded from params). */
  entityArg: string;
}

/**
 * tool name -> ToolBinding. Unmapped tools are "no KIFF opinion": the
 * guard clears + audits them, so attaching the guard never breaks a tool
 * the user has not classified yet (observe-friendly default).
 */
export class ToolMap {
  private readonly bindings = new Map<string, ToolBinding>();

  constructor(bindings?: Record<string, ToolBinding>) {
    if (bindings) {
      for (const [tool, b] of Object.entries(bindings)) {
        this.bindings.set(tool, b);
      }
    }
  }

  bind(tool: string, action: string, entityType: string, entityArg: string): this {
    this.bindings.set(tool, { action, entityType, entityArg });
    return this;
  }

  get(tool: string): ToolBinding | undefined {
    return this.bindings.get(tool);
  }
}

export interface HTTPClientOptions {
  apiKey: string;
  toolMap: ToolMap;
  baseUrl?: string;
  timeoutMs?: number;
  /** injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
}

/** Real client for the cloud decide endpoint. */
export class HTTPClient implements Client {
  private readonly apiKey: string;
  private readonly toolMap: ToolMap;
  private readonly base: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: HTTPClientOptions) {
    if (!opts.apiKey) {
      throw new Error("apiKey is required");
    }
    this.apiKey = opts.apiKey;
    this.toolMap = opts.toolMap;
    this.base = (opts.baseUrl ?? "https://api.kiff.dev").replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    const f = opts.fetchImpl ?? globalThis.fetch;
    if (typeof f !== "function") {
      throw new Error("no fetch available; pass fetchImpl or run on Node >= 18");
    }
    this.fetchImpl = f;
  }

  async decide(
    _tenant: string,
    agent: string,
    tool: string,
    args: Record<string, unknown>,
  ): Promise<Decision> {
    const binding = this.toolMap.get(tool);

    // Unmapped tool: no action to propose. Cleared + audited.
    if (!binding) {
      return new Decision(ALLOWED, `${tool} unmapped; cleared and audited`);
    }

    const entityId = args[binding.entityArg];
    if (entityId === undefined || entityId === null) {
      return new Decision(
        INVALID,
        `tool ${tool}: entity arg '${binding.entityArg}' missing from call`,
      );
    }

    const parameters: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(args)) {
      if (k !== binding.entityArg) parameters[k] = v;
    }

    const body = {
      entity_id: String(entityId),
      entity_type: binding.entityType,
      action_name: binding.action,
      actor_id: agent,
      parameters,
    };

    const { status, payload } = await this.post("/v1/proposals/decide", body);
    const outcome = payload && typeof payload.outcome === "string" ? payload.outcome : "";
    if (!outcome) {
      // Never fail open silently: no outcome -> invalid, and the guard's
      // enforce path holds on any non-allowed outcome.
      return new Decision(INVALID, `decide returned status ${status} with no outcome`);
    }

    const reasons = Array.isArray(payload.reasons) ? (payload.reasons as unknown[]) : [];
    const message = typeof payload.message === "string" ? payload.message : "";
    const reason = message || (reasons.length ? reasons.join(", ") : outcome);
    const proposalId = typeof payload.proposal_id === "string" ? payload.proposal_id : "";
    return new Decision(outcome, reason, proposalId);
  }

  private async post(
    path: string,
    body: Record<string, unknown>,
  ): Promise<{ status: number; payload: Record<string, any> }> {
    const url = this.base + path;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const resp = await this.fetchImpl(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const raw = await resp.text();
      let payload: Record<string, any> = {};
      if (raw) {
        try {
          payload = JSON.parse(raw);
        } catch {
          payload = { raw };
        }
      }
      return { status: resp.status, payload };
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      return { status: 0, payload: { outcome: "", message: `transport error: ${reason}` } };
    } finally {
      clearTimeout(timer);
    }
  }
}
