import { describe, it, expect } from "vitest";
import { Guard } from "../guard.js";
import { Decision } from "../decision.js";
import type { Client } from "../client.js";
import {
  kiffBeforeToolCall,
  registerKiffGuard,
  type BeforeToolCallEvent,
  type OpenClawPluginApi,
  type BeforeToolCallResult,
} from "./openclaw.js";

class StubClient implements Client {
  calls = 0;
  constructor(private readonly outcome = "allowed", private readonly reason = "", private readonly raises = false) {}
  async decide(): Promise<Decision> {
    this.calls += 1;
    if (this.raises) throw new Error("transport down");
    return new Decision(this.outcome, this.reason, "prop_1");
  }
}

const ev = (tool: string, params: Record<string, unknown>): BeforeToolCallEvent => ({
  toolName: tool,
  params,
  toolCallId: "tc",
});

describe("openclaw before_tool_call", () => {
  it("observe never blocks and records observed", async () => {
    const guard = new Guard({ mode: "observe", agent: "oc" });
    const hook = kiffBeforeToolCall(guard);
    const out = await hook(ev("terminal", { command: "rm -rf /" }));
    expect(out).toBeUndefined(); // proceed
    expect(guard.receipts.at(-1)!.state).toBe("observed");
  });

  it("enforce allowed returns undefined and records one executed receipt", async () => {
    const stub = new StubClient("allowed");
    const guard = new Guard({ client: stub, tenant: "t", mode: "enforce", agent: "oc" });
    const out = await kiffBeforeToolCall(guard)(ev("read_file", { path: "x" }));
    expect(out).toBeUndefined();
    expect(guard.receipts.length).toBe(1);
    expect(guard.receipts.at(-1)!.executed).toBe(true);
  });

  it("enforce blocked returns { block: true } and records one withheld receipt", async () => {
    const stub = new StubClient("blocked", "blocked by policy");
    const guard = new Guard({ client: stub, tenant: "t", mode: "enforce", agent: "oc" });
    const out = (await kiffBeforeToolCall(guard)(ev("delete_account", { account_id: "a9" }))) as BeforeToolCallResult;
    expect(out.block).toBe(true);
    expect(out.blockReason).toContain("withheld");
    expect(guard.receipts.length).toBe(1);
    expect(guard.receipts.at(-1)!.executed).toBe(false);
  });

  it("approval_required renders as native requireApproval (the flagship outcome)", async () => {
    const stub = new StubClient("approval_required", "needs a manager");
    const guard = new Guard({ client: stub, tenant: "t", mode: "enforce", agent: "oc" });
    const out = (await kiffBeforeToolCall(guard)(ev("refund_order", { order_id: "o1" }))) as BeforeToolCallResult;
    expect(out.requireApproval).toBeDefined();
    expect(out.requireApproval!.title).toContain("refund_order");
    expect(out.requireApproval!.timeoutBehavior).toBe("deny"); // fail closed on timeout
    expect(out.block).toBeUndefined();
    // still exactly one governed receipt, executed=false
    expect(guard.receipts.length).toBe(1);
    expect(guard.receipts.at(-1)!.executed).toBe(false);
  });

  it("fail-closed on transport error blocks", async () => {
    const stub = new StubClient("allowed", "", true);
    const guard = new Guard({ client: stub, tenant: "t", mode: "enforce", agent: "oc" });
    const out = (await kiffBeforeToolCall(guard, { failClosed: true })(ev("terminal", { command: "ls" }))) as BeforeToolCallResult;
    expect(out.block).toBe(true);
    expect(out.blockReason).toContain("fail-closed");
  });

  it("fail-open when configured lets the tool proceed", async () => {
    const stub = new StubClient("allowed", "", true);
    const guard = new Guard({ client: stub, tenant: "t", mode: "enforce", agent: "oc" });
    const out = await kiffBeforeToolCall(guard, { failClosed: false })(ev("terminal", { command: "ls" }));
    expect(out).toBeUndefined();
  });

  it("unknown outcome fails safe (blocks)", async () => {
    const stub = new StubClient("quarantined", "unknown future outcome");
    const guard = new Guard({ client: stub, tenant: "t", mode: "enforce", agent: "oc" });
    const out = (await kiffBeforeToolCall(guard)(ev("delete_account", { account_id: "a9" }))) as BeforeToolCallResult;
    expect(out.block).toBe(true);
    expect(guard.receipts.at(-1)!.executed).toBe(false);
  });

  it("registerKiffGuard wires before_tool_call with a priority", () => {
    const guard = new Guard({ mode: "observe" });
    const registered: { hook: string; priority?: number }[] = [];
    const api: OpenClawPluginApi = {
      on(hook, _handler, opts) {
        registered.push({ hook, priority: opts?.priority });
      },
    };
    registerKiffGuard(api, guard);
    expect(registered.length).toBe(1);
    expect(registered[0]!.hook).toBe("before_tool_call");
    expect(registered[0]!.priority).toBe(50);
  });
});
