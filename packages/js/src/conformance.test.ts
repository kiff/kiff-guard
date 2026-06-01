/**
 * conformance — the contract every guard adapter must satisfy, ported
 * from the Python suite. An adapter is conformant if, driven through its
 * own seam, it upholds:
 *
 *   OBSERVE (decide-independent):
 *     O1 observe never calls the client
 *     O2 observe always lets the tool run
 *     O3 observe records exactly ONE receipt, state="observed"
 *     O4 observe learns the catalog
 *     O5 observe works with no client and no tenant
 *   ENFORCE:
 *     E1 allowed   -> tool runs; one governed receipt, executed=true
 *     E2 withheld  -> tool does NOT run; one governed receipt, executed=false
 *     E3 roles are never injected by the guard (trust boundary)
 *     E4 an UNKNOWN outcome fails SAFE — withholds, one receipt executed=false
 *
 * An adapter supplies a `drive` shim: invoke its seam once, return whether
 * the tool body ran. The invariants live here, once.
 */

import { describe, it, expect } from "vitest";
import { Guard } from "./guard.js";
import { Decision } from "./decision.js";
import type { Client } from "./client.js";
import { kiffBeforeToolCall, type BeforeToolCallEvent } from "./adapters/openclaw.js";

/** A decide() stub the suite controls. */
class ConformanceClient implements Client {
  calls = 0;
  seenArgs: Record<string, unknown>[] = [];
  constructor(private readonly outcome = "allowed", private readonly reason = "") {}
  async decide(_t: string, _a: string, _tool: string, args: Record<string, unknown>): Promise<Decision> {
    this.calls += 1;
    this.seenArgs.push({ ...args });
    return new Decision(this.outcome, this.reason, "p_conf");
  }
}

type Driver = (guard: Guard, tool: string, args: Record<string, unknown>) => Promise<boolean>;

async function runConformance(name: string, drive: Driver): Promise<void> {
  // O5 + O1: observe works with NO client, and never decides.
  {
    const guard = new Guard({ mode: "observe", agent: "conf" });
    const ran = await drive(guard, "send_email", { to: "x", body: "y" });
    expect(ran, `[${name}] O2: observe must let the tool run`).toBe(true);
    expect(guard.receipts.length, `[${name}] O3: one observed receipt`).toBe(1);
    expect(guard.receipts[0]!.state, `[${name}] O3: state observed`).toBe("observed");
    expect(guard.catalog.tools.get("send_email"), `[${name}] O4: learns catalog`).toEqual(
      new Set(["to", "body"]),
    );
  }
  // O1 explicit: even with a client present, observe must not call it.
  {
    const spy = new ConformanceClient("blocked");
    const guard = new Guard({ client: spy, tenant: "t", mode: "observe", agent: "conf" });
    await drive(guard, "refund", { order_id: "o1" });
    expect(spy.calls, `[${name}] O1: observe must NOT call the client`).toBe(0);
  }
  // E1: allowed -> runs + one governed executed=true.
  {
    const client = new ConformanceClient("allowed");
    const guard = new Guard({ client, tenant: "t", mode: "enforce", agent: "conf" });
    const ran = await drive(guard, "refund", { order_id: "o1", amount_cents: 5 });
    expect(ran, `[${name}] E1: allowed must run the tool`).toBe(true);
    const gov = guard.receipts.filter((r) => r.state === "governed");
    expect(gov.length, `[${name}] E1: one governed receipt`).toBe(1);
    expect(gov[0]!.executed, `[${name}] E1: executed=true`).toBe(true);
    expect(client.calls, `[${name}] E1: client called once`).toBe(1);
  }
  // E2: withheld -> no run + one governed executed=false.
  {
    const client = new ConformanceClient("blocked", "blocked by policy");
    const guard = new Guard({ client, tenant: "t", mode: "enforce", agent: "conf" });
    const ran = await drive(guard, "delete_account", { account_id: "a9" });
    expect(ran, `[${name}] E2: withheld must NOT run the tool`).toBe(false);
    const gov = guard.receipts.filter((r) => r.state === "governed");
    expect(gov.length, `[${name}] E2: one governed receipt`).toBe(1);
    expect(gov[0]!.executed, `[${name}] E2: executed=false`).toBe(false);
  }
  // E3: roles are never injected by the guard.
  {
    const client = new ConformanceClient("allowed");
    const guard = new Guard({ client, tenant: "t", mode: "enforce", agent: "conf" });
    await drive(guard, "refund", { order_id: "o1", actor_roles: ["admin"] });
    for (const seen of client.seenArgs) {
      expect("roles" in seen, `[${name}] E3: guard must never inject a top-level 'roles'`).toBe(false);
    }
  }
  // E4: an unknown outcome must fail SAFE (withhold).
  {
    const client = new ConformanceClient("quarantined", "unknown future outcome");
    const guard = new Guard({ client, tenant: "t", mode: "enforce", agent: "conf" });
    const ran = await drive(guard, "delete_account", { account_id: "a9" });
    expect(ran, `[${name}] E4: unknown outcome must NOT run the tool`).toBe(false);
    const gov = guard.receipts.filter((r) => r.state === "governed");
    expect(gov.length, `[${name}] E4: one governed receipt`).toBe(1);
    expect(gov[0]!.executed, `[${name}] E4: executed=false`).toBe(false);
  }
}

// --- OpenClaw driver: vote. Returns block/approval/undefined; OpenClaw
//     runs the tool iff the hook returns nothing. "ran" = not blocked. ---
const driveOpenClaw: Driver = async (guard, tool, args) => {
  const hook = kiffBeforeToolCall(guard);
  const event: BeforeToolCallEvent = { toolName: tool, params: args, toolCallId: "tc" };
  const out = await hook(event);
  const blocked = out !== undefined && (out.block === true || out.requireApproval !== undefined);
  return !blocked;
};

describe("conformance", () => {
  it("openclaw passes the full suite", async () => {
    await runConformance("openclaw", driveOpenClaw);
  });
});
