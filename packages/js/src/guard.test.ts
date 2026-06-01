import { describe, it, expect } from "vitest";
import { Guard } from "./guard.js";
import { Decision, Hold } from "./decision.js";
import type { Client } from "./client.js";

class StubClient implements Client {
  calls = 0;
  constructor(private readonly outcome = "allowed", private readonly reason = "", private readonly raises = false) {}
  async decide(): Promise<Decision> {
    this.calls += 1;
    if (this.raises) throw new Error("transport down");
    return new Decision(this.outcome, this.reason, "prop_1");
  }
}

describe("Decision", () => {
  it("allowed only for exactly 'allowed'", () => {
    expect(new Decision("allowed").allowed).toBe(true);
    expect(new Decision("blocked").allowed).toBe(false);
  });
  it("withheld is the negation of allowed (fail-safe on unknown)", () => {
    expect(new Decision("allowed").withheld).toBe(false);
    expect(new Decision("blocked").withheld).toBe(true);
    expect(new Decision("approval_required").withheld).toBe(true);
    expect(new Decision("quarantined").withheld).toBe(true); // unknown -> withhold
  });
});

describe("Guard constructor", () => {
  it("rejects an invalid mode", () => {
    // @ts-expect-error invalid mode
    expect(() => new Guard({ mode: "nope" })).toThrow(/mode must be/);
  });
  it("enforce requires a client", () => {
    expect(() => new Guard({ mode: "enforce" })).toThrow(/enforce mode requires a client/);
  });
  it("observe works with no client", () => {
    const g = new Guard({ mode: "observe" });
    expect(g.mode).toBe("observe");
  });
});

describe("observe", () => {
  it("records observed + learns catalog, no client needed", () => {
    const g = new Guard({ mode: "observe", agent: "a" });
    g.observe("terminal", { command: "ls" });
    expect(g.receipts.at(-1)!.state).toBe("observed");
    expect(g.catalog.tools.get("terminal")).toEqual(new Set(["command"]));
  });
});

describe("decideOnly", () => {
  it("decides + returns but does NOT record (one-receipt rule)", async () => {
    const stub = new StubClient("approval_required", "", false);
    const g = new Guard({ client: stub, tenant: "t", mode: "enforce", agent: "a" });
    const d = await g.decideOnly("write_file", { path: "/etc/x" });
    expect(stub.calls).toBe(1);
    expect(d.outcome).toBe("approval_required");
    expect(g.receipts.length).toBe(0); // records nothing
  });
  it("requires a client", async () => {
    const g = new Guard({ mode: "observe" });
    await expect(g.decideOnly("t", {})).rejects.toThrow(/requires a client/);
  });
});

describe("record helpers", () => {
  it("recordExecuted writes exactly one governed executed=true", async () => {
    const stub = new StubClient("allowed");
    const g = new Guard({ client: stub, tenant: "t", mode: "enforce" });
    const d = await g.decideOnly("terminal", { command: "ls" });
    g.recordExecuted("terminal", { command: "ls" }, d);
    expect(g.receipts.length).toBe(1);
    expect(g.receipts.at(-1)!.executed).toBe(true);
  });
  it("recordWithheld writes exactly one governed executed=false", async () => {
    const stub = new StubClient("blocked");
    const g = new Guard({ client: stub, tenant: "t", mode: "enforce" });
    const d = await g.decideOnly("delete_account", { account_id: "a9" });
    g.recordWithheld("delete_account", { account_id: "a9" }, d);
    expect(g.receipts.length).toBe(1);
    expect(g.receipts.at(-1)!.executed).toBe(false);
  });
});

describe("evaluate (middleware convenience)", () => {
  it("observe runs the tool + records observed", async () => {
    const g = new Guard({ mode: "observe" });
    let ran = false;
    const out = await g.evaluate("t", {}, () => {
      ran = true;
      return "ok";
    });
    expect(ran).toBe(true);
    expect(out).toBe("ok");
    expect(g.receipts.at(-1)!.state).toBe("observed");
  });
  it("enforce allowed runs + one governed receipt", async () => {
    const stub = new StubClient("allowed");
    const g = new Guard({ client: stub, tenant: "t", mode: "enforce" });
    let ran = false;
    await g.evaluate("t", {}, () => {
      ran = true;
    });
    expect(ran).toBe(true);
    expect(g.receipts.filter((r) => r.state === "governed").length).toBe(1);
  });
  it("enforce withheld throws Hold + tool never runs", async () => {
    const stub = new StubClient("blocked", "nope");
    const g = new Guard({ client: stub, tenant: "t", mode: "enforce" });
    let ran = false;
    await expect(
      g.evaluate("t", {}, () => {
        ran = true;
      }),
    ).rejects.toBeInstanceOf(Hold);
    expect(ran).toBe(false);
    expect(g.receipts.at(-1)!.executed).toBe(false);
  });
});
