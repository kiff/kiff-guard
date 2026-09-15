/**
 * Run context: the facts a harness asserts that the model cannot.
 *
 * kiff-cloud RFC 039. Mirrors the Python suite (tests/test_run_context.py)
 * so the two SDKs cannot drift on the properties that make the assertion
 * worth anything: the model has no route to clearing it, and a guard that
 * never opts in sends nothing rather than silently claiming a clean run.
 */

import { describe, expect, it } from "vitest";
import { Guard } from "./guard.js";
import { Decision, ALLOWED } from "./decision.js";

/** Captures the runContext each decide() received. */
class CtxClient {
  contexts: Array<Record<string, unknown> | undefined> = [];
  calls = 0;

  async decide(
    _t: string,
    _a: string,
    _tool: string,
    _args: Record<string, unknown>,
    runContext?: Record<string, unknown>,
  ): Promise<Decision> {
    this.calls += 1;
    this.contexts.push(runContext);
    return new Decision(ALLOWED, "", "prop_1");
  }
}

/** A Client written before run context existed. It must keep working. */
class LegacyClient {
  calls = 0;
  async decide(
    _t: string,
    _a: string,
    _tool: string,
    _args: Record<string, unknown>,
  ): Promise<Decision> {
    this.calls += 1;
    return new Decision(ALLOWED, "", "p");
  }
}

const run = () => "ran";

describe("opt-in", () => {
  it("sends nothing and works with a legacy client when never opted in", async () => {
    const legacy = new LegacyClient();
    const guard = new Guard({ client: legacy, mode: "enforce", tenant: "t", agent: "a" });
    expect(guard.runContext()).toBeUndefined();
    await guard.evaluate("refund_order", { id: "o1" }, run);
    expect(legacy.calls).toBe(1);
  });

  it("opts in when untrusted tools are declared", async () => {
    const spy = new CtxClient();
    const guard = new Guard({
      client: spy, mode: "enforce", tenant: "t", agent: "a",
      untrustedTools: ["read_public_issue"],
    });
    await guard.evaluate("refund_order", { id: "o1" }, run);
    expect(spy.contexts.at(-1)).toEqual({ untrusted_input: false });
  });

  it("sends the run id when set", async () => {
    const spy = new CtxClient();
    const guard = new Guard({ client: spy, mode: "enforce", tenant: "t", agent: "a", runId: "run-7" });
    await guard.evaluate("refund_order", { id: "o1" }, run);
    expect(spy.contexts.at(-1)).toEqual({ untrusted_input: false, run_id: "run-7" });
  });
});

describe("the taint itself", () => {
  it("taints subsequent calls, not the untrusted read itself", async () => {
    const spy = new CtxClient();
    const guard = new Guard({
      client: spy, mode: "enforce", tenant: "t", agent: "a",
      untrustedTools: ["read_public_issue"],
    });

    await guard.evaluate("read_public_issue", { id: "i1" }, run);
    expect(spy.contexts[0]).toEqual({ untrusted_input: false });

    await guard.evaluate("post_comment", { id: "i1" }, run);
    expect(spy.contexts[1]).toEqual({ untrusted_input: true });
  });

  it("is monotonic within a run", async () => {
    const spy = new CtxClient();
    const guard = new Guard({
      client: spy, mode: "enforce", tenant: "t", agent: "a",
      untrustedTools: ["fetch_url"],
    });
    await guard.evaluate("fetch_url", { id: "u" }, run);
    for (let i = 0; i < 3; i += 1) {
      await guard.evaluate("refund_order", { id: "o1" }, run);
    }
    for (const ctx of spy.contexts.slice(1)) {
      expect(ctx).toEqual({ untrusted_input: true });
    }
  });

  it("taints and opts in on a manual mark", async () => {
    const spy = new CtxClient();
    const guard = new Guard({ client: spy, mode: "enforce", tenant: "t", agent: "a" });
    expect(guard.runContext()).toBeUndefined();
    guard.markUntrustedInput("webhook_body");
    await guard.evaluate("refund_order", { id: "o1" }, run);
    expect(spy.contexts.at(-1)).toEqual({ untrusted_input: true });
  });

  it("exposes no public way to clear taint", () => {
    const guard = new Guard({ mode: "observe", agent: "a", untrustedTools: ["fetch_url"] });
    guard.markUntrustedInput();
    expect(guard.untrustedInput).toBe(true);

    for (const name of ["clear", "untaint", "resetTaint", "clearUntrustedInput"]) {
      expect((guard as unknown as Record<string, unknown>)[name]).toBeUndefined();
    }

    // untrustedInput is a getter with no setter: assigning must not stick.
    try {
      (guard as unknown as Record<string, unknown>).untrustedInput = false;
    } catch {
      // strict mode throws on assigning to a getter-only property
    }
    expect(guard.untrustedInput).toBe(true);
  });

  it("clears for a new run via startRun", async () => {
    const spy = new CtxClient();
    const guard = new Guard({
      client: spy, mode: "enforce", tenant: "t", agent: "a",
      untrustedTools: ["fetch_url"],
    });
    await guard.evaluate("fetch_url", { id: "u" }, run);
    await guard.evaluate("refund_order", { id: "o1" }, run);
    expect(spy.contexts.at(-1)).toEqual({ untrusted_input: true });

    guard.startRun("run-2");
    await guard.evaluate("refund_order", { id: "o1" }, run);
    expect(spy.contexts.at(-1)).toEqual({ untrusted_input: false, run_id: "run-2" });
  });
});

describe("vote shape", () => {
  it("taints on recordExecuted, where the guard learns the tool ran", async () => {
    const spy = new CtxClient();
    const guard = new Guard({
      client: spy, mode: "enforce", tenant: "t", agent: "a",
      untrustedTools: ["read_public_issue"],
    });

    const d = await guard.decideOnly("read_public_issue", { id: "i1" });
    guard.recordExecuted("read_public_issue", { id: "i1" }, d);

    await guard.decideOnly("post_comment", { id: "i1" });
    expect(spy.contexts.at(-1)).toEqual({ untrusted_input: true });
  });

  it("tracks the run in observe mode too", async () => {
    const guard = new Guard({ mode: "observe", agent: "a", untrustedTools: ["read_public_issue"] });
    await guard.evaluate("read_public_issue", { id: "i1" }, run);
    expect(guard.untrustedInput).toBe(true);
  });
});
