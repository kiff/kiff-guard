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

/** Runtime metadata sent to KIFF Cloud when a guard opts into discovery. */
export interface GuardConnectInput {
  agentId: string;
  adapter: string;
  mode: "observe" | "enforce";
  project?: string;
  environment?: string;
  workflow?: string;
  sdkVersion?: string;
}

/** Cloud's last-known runtime row for one tenant/project/env/agent/workflow. */
export interface GuardConnection {
  tenantId?: string;
  project: string;
  environment: string;
  agentId: string;
  workflow: string;
  adapter: string;
  sdkVersion?: string;
  mode: "observe" | "enforce";
  firstSeenAt?: string;
  lastSeenAt?: string;
  seenCount?: number;
}

export interface GuardToolObservation {
  name: string;
  description?: string;
  parameterSchema?: Record<string, unknown>;
  entityArg?: string;
  action?: string;
  entityType?: string;
  required?: string[];
  observedCallCount?: number;
}

export interface GuardObservationInput extends GuardConnectInput {
  tools: GuardToolObservation[];
}

export interface GuardObservation {
  tenantId?: string;
  project: string;
  environment: string;
  agentId: string;
  workflow: string;
  tools: GuardToolObservation[];
  observedAt?: string;
  updatedAt?: string;
}

/** Optional client capability for registering a live guard runtime. */
export interface GuardConnector {
  connectGuard(input: GuardConnectInput): Promise<GuardConnection>;
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

  async connectGuard(input: GuardConnectInput): Promise<GuardConnection> {
    if (!input.agentId) {
      throw new Error("agentId is required");
    }
    if (!input.adapter) {
      throw new Error("adapter is required");
    }

    const body: Record<string, unknown> = {
      agent_id: input.agentId,
      adapter: input.adapter,
      mode: input.mode,
    };
    if (input.project) body.project = input.project;
    if (input.environment) body.environment = input.environment;
    if (input.workflow) body.workflow = input.workflow;
    if (input.sdkVersion) body.sdk_version = input.sdkVersion;

    const { status, payload } = await this.post("/v1/guard/connect", body);
    if (status === 0) {
      const message = typeof payload.message === "string" ? payload.message : "transport error";
      throw new Error(message);
    }
    if (status < 200 || status >= 300) {
      const message = typeof payload.error === "string" ? payload.error : `connect returned status ${status}`;
      throw new Error(message);
    }

    return normalizeGuardConnection(payload);
  }

  async observeGuard(input: GuardObservationInput): Promise<GuardObservation> {
    if (!input.agentId) {
      throw new Error("agentId is required");
    }
    if (!input.adapter) {
      throw new Error("adapter is required");
    }

    const body: Record<string, unknown> = {
      agent_id: input.agentId,
      adapter: input.adapter,
      mode: input.mode,
      tools: input.tools.map(wireToolObservation),
    };
    if (input.project) body.project = input.project;
    if (input.environment) body.environment = input.environment;
    if (input.workflow) body.workflow = input.workflow;
    if (input.sdkVersion) body.sdk_version = input.sdkVersion;

    const { status, payload } = await this.post("/v1/guard/observations", body);
    if (status === 0) {
      const message = typeof payload.message === "string" ? payload.message : "transport error";
      throw new Error(message);
    }
    if (status < 200 || status >= 300) {
      const message =
        typeof payload.error === "string" ? payload.error : `observations returned status ${status}`;
      throw new Error(message);
    }

    return normalizeGuardObservation(payload.observation ?? payload);
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

function wireToolObservation(tool: GuardToolObservation): Record<string, unknown> {
  const body: Record<string, unknown> = { name: tool.name };
  if (tool.description) body.description = tool.description;
  if (tool.parameterSchema) body.parameter_schema = tool.parameterSchema;
  if (tool.entityArg) body.entity_arg = tool.entityArg;
  if (tool.action) body.action = tool.action;
  if (tool.entityType) body.entity_type = tool.entityType;
  if (tool.required) body.required = tool.required;
  if (tool.observedCallCount !== undefined) body.observed_call_count = tool.observedCallCount;
  return body;
}

function normalizeGuardConnection(payload: Record<string, any>): GuardConnection {
  const mode = payload.mode === "enforce" ? "enforce" : "observe";
  return {
    tenantId: stringOrUndefined(payload.tenant_id),
    project: stringOrDefault(payload.project, "default"),
    environment: stringOrDefault(payload.environment, "dev"),
    agentId: stringOrDefault(payload.agent_id, ""),
    workflow: stringOrDefault(payload.workflow, "default"),
    adapter: stringOrDefault(payload.adapter, ""),
    sdkVersion: stringOrUndefined(payload.sdk_version),
    mode,
    firstSeenAt: stringOrUndefined(payload.first_seen_at),
    lastSeenAt: stringOrUndefined(payload.last_seen_at),
    seenCount: typeof payload.seen_count === "number" ? payload.seen_count : undefined,
  };
}

function normalizeGuardObservation(payload: Record<string, any>): GuardObservation {
  const tools = Array.isArray(payload.tools)
    ? payload.tools.map((tool: Record<string, any>) => ({
        name: stringOrDefault(tool.name, ""),
        description: stringOrUndefined(tool.description),
        parameterSchema:
          tool.parameter_schema && typeof tool.parameter_schema === "object"
            ? tool.parameter_schema
            : undefined,
        entityArg: stringOrUndefined(tool.entity_arg),
        action: stringOrUndefined(tool.action),
        entityType: stringOrUndefined(tool.entity_type),
        required: Array.isArray(tool.required)
          ? tool.required.filter((v: unknown): v is string => typeof v === "string")
          : undefined,
        observedCallCount:
          typeof tool.observed_call_count === "number" ? tool.observed_call_count : undefined,
      }))
    : [];
  return {
    tenantId: stringOrUndefined(payload.tenant_id),
    project: stringOrDefault(payload.project, "default"),
    environment: stringOrDefault(payload.environment, "dev"),
    agentId: stringOrDefault(payload.agent_id, ""),
    workflow: stringOrDefault(payload.workflow, "default"),
    tools,
    observedAt: stringOrUndefined(payload.observed_at),
    updatedAt: stringOrUndefined(payload.updated_at),
  };
}

function stringOrDefault(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
