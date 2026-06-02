import { describe, expect, it } from "vitest";
import { HTTPClient, ToolMap } from "./client.js";

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
