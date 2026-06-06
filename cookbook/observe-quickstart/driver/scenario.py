"""scenario — prove observe mode end to end, with no KIFF account.

Default (offline) path: replays a scripted transcript of tool calls
through the real agno_hook(guard) — no LLM, no network, no API keys.
Live path: set OPENAI_API_KEY and pass --live to run a real Agno agent.

Either way the result is the same: a real audit trail of every tool call
and a derived starter domain — produced with `Guard(mode="observe")` and
nothing else (no client, no tenant, no kiff-decide gate, no cloud).

Run:
    python3 driver/scenario.py            # offline, zero keys
    OPENAI_API_KEY=... python3 driver/scenario.py --live
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from kiff_guard import export_yaml  # noqa: E402
from support_agent import build_guard, create_support_agent, SCRIPTED_CALLS  # noqa: E402


def run_offline(guard):
    """Replay the scripted transcript through the real agno adapter."""
    from kiff_guard.adapters.agno import agno_hook
    hook = agno_hook(guard)

    def _run_tool(**kwargs):
        return "ok"  # the tool body; observe never blocks it

    print("Replaying a scripted agent transcript through agno_hook (observe)...\n")
    for name, kwargs in SCRIPTED_CALLS:
        hook(name, _run_tool, kwargs)
        print(f"  ran {name}({', '.join(kwargs)})")
    print()


def run_live(guard):
    """Run a real Agno agent (needs OPENAI_API_KEY)."""
    agent = create_support_agent(guard)
    prompts = [
        "Refund order ord_1001 for 2500 cents — the item arrived damaged — and email alice@example.com to confirm.",
        "Escalate ticket tkt_77 to high priority.",
    ]
    print("Running a live Agno agent (gpt-4o-mini) in observe mode...\n")
    for p in prompts:
        resp = agent.run(p)
        content = resp.content if hasattr(resp, "content") else str(resp)
        print(f"  > {p}\n    {content[:120]}\n")


def main():
    live = "--live" in sys.argv
    guard = build_guard()

    if live and os.environ.get("OPENAI_API_KEY"):
        run_live(guard)
    else:
        if live:
            print("(--live requested but OPENAI_API_KEY not set; running offline)\n")
        run_offline(guard)

    # --- The observe payoff: a real audit trail, no KIFF account ---------
    print("=" * 60)
    print(f"AUDIT TRAIL — {len(guard.receipts)} observed receipt(s)")
    print("=" * 60)
    for r in guard.receipts:
        print(f"  [{r.state}] {r.tool}  ({r.outcome})")

    print()
    print("=" * 60)
    print("DERIVED DOMAIN DRAFT (from observed traffic)")
    print("=" * 60)
    print(export_yaml("support-ops", guard.catalog))

    # Every receipt is "observed" — observe never decides, never blocks.
    assert all(r.state == "observed" for r in guard.receipts), "observe must only record observed receipts"
    assert guard.client is None, "observe ran with no client — no KIFF account needed"
    print("PROOF: every tool ran and was audited with no KIFF account, "
          "no tenant, no gate, no API call. Exit 0.")


if __name__ == "__main__":
    main()
