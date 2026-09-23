import { describe, expect, it } from "vitest";
import { HTTPClient, ToolMap } from "./client.js";

describe("HTTPClient.decide — domain selection", () => {
  it("sends a selected domain as a proposal field", async () => {
    let body: Record<string, unknown> = {};
    const client = new HTTPClient({
      apiKey: "kiff_live_test",
      toolMap: new ToolMap().bind("refund", "REFUND", "Order", "order_id"),
      domain: "card-refund",
      fetchImpl: async (_url, init) => {
        body = JSON.parse(init?.body as string);
        return new Response(JSON.stringify({ outcome: "allowed" }), { status: 200 });
      },
    });
    await client.decide("t", "agent", "refund", { order_id: "o1" });
    expect(body.domain).toBe("card-refund");
    expect(body.parameters).toEqual({});
  });

  it("omits domain when using the tenant default", async () => {
    let body: Record<string, unknown> = {};
    const client = new HTTPClient({
      apiKey: "kiff_live_test",
      toolMap: new ToolMap().bind("refund", "REFUND", "Order", "order_id"),
      fetchImpl: async (_url, init) => {
        body = JSON.parse(init?.body as string);
        return new Response(JSON.stringify({ outcome: "allowed" }), { status: 200 });
      },
    });
    await client.decide("t", "agent", "refund", { order_id: "o1" });
    expect(body).not.toHaveProperty("domain");
  });
});

describe("HTTPClient.connectGuard", () => {
  it("posts guard runtime metadata to KIFF Cloud", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const fetchImpl: typeof fetch = async (url, init) => {
      calls.push({ url: String(url), init: init ?? {} });
      return new Response(
        JSON.stringify({
          tenant_id: "tenant_1",
          project: "payments",
          environment: "prod",
          agent_id: "ap-agent",
          workflow: "duplicate-payment",
          adapter: "openclaw",
          sdk_version: "0.1.0",
          mode: "enforce",
          seen_count: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    };

    const client = new HTTPClient({
      apiKey: "kiff_live_test",
      toolMap: new ToolMap(),
      baseUrl: "https://api.example.test/",
      fetchImpl,
    });

    const connection = await client.connectGuard({
      agentId: "ap-agent",
      adapter: "openclaw",
      mode: "enforce",
      project: "payments",
      environment: "prod",
      workflow: "duplicate-payment",
      sdkVersion: "0.1.0",
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe("https://api.example.test/v1/guard/connect");
    expect(calls[0]!.init.method).toBe("POST");
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBe("Bearer kiff_live_test");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({
      agent_id: "ap-agent",
      adapter: "openclaw",
      mode: "enforce",
      project: "payments",
      environment: "prod",
      workflow: "duplicate-payment",
      sdk_version: "0.1.0",
    });
    expect(connection).toMatchObject({
      tenantId: "tenant_1",
      project: "payments",
      environment: "prod",
      agentId: "ap-agent",
      workflow: "duplicate-payment",
      adapter: "openclaw",
      sdkVersion: "0.1.0",
      mode: "enforce",
      seenCount: 1,
    });
  });

  it("fails visibly when Cloud rejects the connection", async () => {
    const fetchImpl: typeof fetch = async () =>
      new Response(JSON.stringify({ error: "invalid adapter" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });

    const client = new HTTPClient({
      apiKey: "kiff_live_test",
      toolMap: new ToolMap(),
      fetchImpl,
    });

    await expect(
      client.connectGuard({ agentId: "ap-agent", adapter: "openclaw", mode: "observe" }),
    ).rejects.toThrow(/invalid adapter/);
  });
});

describe("HTTPClient.observeGuard", () => {
  it("posts an observed tool catalog to KIFF Cloud", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const fetchImpl: typeof fetch = async (url, init) => {
      calls.push({ url: String(url), init: init ?? {} });
      return new Response(
        JSON.stringify({
          observation: {
            tenant_id: "tenant_1",
            project: "cookbook",
            environment: "aws",
            agent_id: "ap-agent",
            workflow: "duplicate-payment",
            tools: [
              {
                name: "pay_invoice",
                entity_arg: "invoice_id",
                action: "PAY_INVOICE",
                entity_type: "Invoice",
                required: ["amount_cents"],
              },
            ],
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    };

    const client = new HTTPClient({
      apiKey: "kiff_live_test",
      toolMap: new ToolMap(),
      baseUrl: "https://api.example.test/",
      fetchImpl,
    });

    const observation = await client.observeGuard({
      agentId: "ap-agent",
      adapter: "openclaw",
      mode: "enforce",
      project: "cookbook",
      environment: "aws",
      workflow: "duplicate-payment",
      sdkVersion: "0.1.0",
      tools: [
        {
          name: "pay_invoice",
          description: "Pay an outstanding invoice",
          entityArg: "invoice_id",
          action: "PAY_INVOICE",
          entityType: "Invoice",
          required: ["amount_cents"],
          parameterSchema: {
            type: "object",
            required: ["invoice_id", "amount_cents"],
          },
        },
      ],
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe("https://api.example.test/v1/guard/observations");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({
      agent_id: "ap-agent",
      adapter: "openclaw",
      mode: "enforce",
      project: "cookbook",
      environment: "aws",
      workflow: "duplicate-payment",
      sdk_version: "0.1.0",
      tools: [
        {
          name: "pay_invoice",
          description: "Pay an outstanding invoice",
          entity_arg: "invoice_id",
          action: "PAY_INVOICE",
          entity_type: "Invoice",
          required: ["amount_cents"],
          parameter_schema: {
            type: "object",
            required: ["invoice_id", "amount_cents"],
          },
        },
      ],
    });
    expect(observation.tools[0]).toMatchObject({
      name: "pay_invoice",
      entityArg: "invoice_id",
      action: "PAY_INVOICE",
      entityType: "Invoice",
    });
  });
});

describe("HTTPClient.decide — unbound tools", () => {
  const apiKey = "kiff_live_t_" + "y".repeat(32);

  // An unbound tool has no action to propose, so KIFF is never asked about it.
  // Synthesizing an "allowed" here is a fail-open whose receipt reads as
  // governed: the call runs, no HTTP request leaves the process, and the
  // ledger claims the runtime cleared it.
  it("withholds by default and never calls KIFF", async () => {
    let calls = 0;
    const fetchImpl: typeof fetch = async () => {
      calls += 1;
      return new Response("{}", { status: 200 });
    };
    const client = new HTTPClient({ apiKey, toolMap: new ToolMap(), fetchImpl });

    const decision = await client.decide("t", "a", "wire_transfer", { amount: 999999 });

    expect(decision.allowed).toBe(false);
    expect(decision.withheld).toBe(true);
    expect(decision.outcome).toBe("invalid");
    expect(decision.reason).toContain("not bound");
    expect(calls).toBe(0);
  });

  it("clears unbound tools only when explicitly opted in", async () => {
    const client = new HTTPClient({
      apiKey,
      toolMap: new ToolMap(),
      unmapped: "allow",
      fetchImpl: async () => new Response("{}", { status: 200 }),
    });

    const decision = await client.decide("t", "a", "wire_transfer", {});

    expect(decision.allowed).toBe(true);
    expect(decision.reason).toContain("unmapped");
  });

  it("rejects an invalid unmapped setting", () => {
    expect(
      () =>
        new HTTPClient({
          apiKey,
          toolMap: new ToolMap(),
          unmapped: "yolo" as unknown as "allow",
        }),
    ).toThrow(/unmapped must be/);
  });
});

describe("HTTPClient.decide — status handling and transport security", () => {
  const apiKey = "kiff_live_t_" + "y".repeat(32);
  const bound = () => new ToolMap().bind("refund_order", "REFUND_ORDER", "Order", "order_id");
  const respond = (status: number, body: unknown): typeof fetch =>
    async () => new Response(JSON.stringify(body), { status });

  it("refuses an allowed outcome arriving on a non-success status", async () => {
    const client = new HTTPClient({
      apiKey,
      toolMap: bound(),
      fetchImpl: respond(500, { outcome: "allowed" }),
    });

    const d = await client.decide("t", "a", "refund_order", { order_id: "o1" });

    expect(d.allowed).toBe(false);
    expect(d.outcome).toBe("invalid");
    expect(d.reason).toContain("non-success status");
  });

  it("still honours withheld outcomes on a non-success status", async () => {
    // KIFF reports limit_exceeded as 429 and invalid as 400 by design; the
    // outcome travels in the body and must be honoured.
    const client = new HTTPClient({
      apiKey,
      toolMap: bound(),
      fetchImpl: respond(429, { outcome: "limit_exceeded" }),
    });

    const d = await client.decide("t", "a", "refund_order", { order_id: "o1" });

    expect(d.outcome).toBe("limit_exceeded");
    expect(d.withheld).toBe(true);
  });

  it("refuses a plaintext baseUrl", () => {
    expect(
      () => new HTTPClient({ apiKey, toolMap: new ToolMap(), baseUrl: "http://api.kiff.dev" }),
    ).toThrow(/not https/);
  });

  it("permits loopback and an explicit opt-in", () => {
    expect(
      () => new HTTPClient({ apiKey, toolMap: new ToolMap(), baseUrl: "http://127.0.0.1:8931" }),
    ).not.toThrow();
    expect(
      () =>
        new HTTPClient({
          apiKey,
          toolMap: new ToolMap(),
          baseUrl: "http://kiff.internal",
          allowInsecureHttp: true,
        }),
    ).not.toThrow();
  });
});
