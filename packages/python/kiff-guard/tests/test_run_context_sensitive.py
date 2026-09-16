"""The second run-context fact: sensitive reads.

kiff-cloud RFC 039 gained a second condition after the prompt-injection
lab measured the first one. Gating on taint alone held 90 of 90 benign
runs, because the agent under test began every run by reading a public
issue — a condition that is always true refuses the same set of actions
as a condition nobody checks. The conjunction of taint and a sensitive
read fires on the chain actually forming instead.

These tests pin the property that makes the second fact safe to add to a
field guards were already sending: a guard that does not track sensitive
reads must send NO key, never `false`. The cloud reads absence as
"unasserted" and refuses; it reads `false` as "it did not happen" and
allows. Only one of those is honest for a guard that was never watching,
and getting it wrong turns a fail-closed into a fail-open.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Decision, Guard  # noqa: E402


class _CtxClient:
    def __init__(self, outcome="allowed"):
        self.contexts = []
        self._d = Decision(outcome=outcome, reason="", proposal_id="prop_1")

    def decide(self, tenant, agent, tool, args, run_context=None):
        self.contexts.append(run_context)
        return self._d


def test_guard_without_sensitive_tools_omits_the_key():
    """The fail-open this shape could have shipped with.

    A guard that tracks taint but knows nothing about sensitive reads
    must not claim there were none."""
    g = Guard(tenant="t", agent="a", untrusted_tools=["read_issue"])
    ctx = g.run_context()
    assert ctx is not None
    assert "sensitive_read" not in ctx


def test_guard_with_sensitive_tools_asserts_false_when_clean():
    """A guard that IS watching is entitled to the negative claim, and
    the cloud needs it — an explicit clean assertion is the only path
    through a gate that depends on the fact."""
    g = Guard(tenant="t", agent="a", sensitive_tools=["read_secret"])
    assert g.run_context()["sensitive_read"] is False


def test_sensitive_tool_marks_the_run():
    g = Guard(tenant="t", agent="a", sensitive_tools=["read_secret"])
    g._note_untrusted_tool("read_secret")
    assert g.sensitive_read is True
    assert g.run_context()["sensitive_read"] is True


def test_manual_mark_turns_tracking_on():
    """A guard that reports a sensitive read is by definition watching
    for them, so the manual path enables the claim as well as making it."""
    g = Guard(tenant="t", agent="a", run_id="r1")
    assert "sensitive_read" not in g.run_context()
    g.mark_sensitive_read("vault:/db/password")
    ctx = g.run_context()
    assert ctx["sensitive_read"] is True


def test_sensitive_read_is_monotonic_within_a_run():
    """No clear()/untaint(). Nothing the model can influence resets it."""
    g = Guard(tenant="t", agent="a", sensitive_tools=["read_secret"])
    g.mark_sensitive_read("x")
    for tool in ("summarize", "post_comment", "read_public"):
        g._note_untrusted_tool(tool)
    assert g.sensitive_read is True


def test_start_run_clears_the_fact_but_not_the_tracking():
    """A guard watching for sensitive reads before a run boundary is
    still watching after it, so the new run's `false` remains a claim it
    is entitled to make."""
    g = Guard(tenant="t", agent="a", run_id="r1")
    g.mark_sensitive_read("x")
    g.start_run("r2")
    ctx = g.run_context()
    assert ctx["sensitive_read"] is False
    assert ctx["run_id"] == "r2"
    assert g.sensitive_read is False


def test_both_facts_travel_on_decide():
    c = _CtxClient()
    g = Guard(client=c, tenant="t", agent="a", mode="enforce", run_id="r1",
              untrusted_tools=["read_issue"], sensitive_tools=["read_secret"])
    g._note_untrusted_tool("read_issue")
    g._note_untrusted_tool("read_secret")
    g._decide("post_comment", {})
    assert c.contexts[-1] == {
        "untrusted_input": True, "sensitive_read": True, "run_id": "r1",
    }


def test_sensitive_tools_alone_opts_into_run_context():
    """Naming sensitive tools is opting in, the same way naming
    untrusted ones is."""
    g = Guard(tenant="t", agent="a", sensitive_tools=["read_secret"])
    assert g.run_context() is not None
