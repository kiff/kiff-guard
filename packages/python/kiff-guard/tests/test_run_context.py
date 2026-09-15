"""Run context: the facts a harness asserts that the model cannot.

kiff-cloud RFC 039. The guard is trusted integrator code, so it is the
right place to assert what happened in a run. These tests pin the two
properties that make the assertion worth anything: the model has no route
to clearing it, and a guard that never opts in sends nothing rather than
silently claiming a clean run.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import Decision, Guard  # noqa: E402


class _CtxClient:
    """Captures the run_context each decide() received, and works whether
    or not the kwarg is passed — like a pre-RFC-039 client would not."""

    def __init__(self, outcome="allowed"):
        self.contexts = []
        self.calls = 0
        self._d = Decision(outcome=outcome, reason="", proposal_id="prop_1")

    def decide(self, tenant, agent, tool, args, run_context=None):
        self.calls += 1
        self.contexts.append(run_context)
        return self._d


class _LegacyClient:
    """A Client written before run context existed. It must keep working."""

    def __init__(self):
        self.calls = 0

    def decide(self, tenant, agent, tool, args):
        self.calls += 1
        return Decision(outcome="allowed", reason="", proposal_id="p")


def _runner():
    return lambda: "ran"


# ---- opt-in ---------------------------------------------------------------

def test_guard_without_run_context_sends_none_and_works_with_a_legacy_client():
    legacy = _LegacyClient()
    guard = Guard(client=legacy, mode="enforce", tenant="t", agent="a")
    assert guard.run_context() is None
    guard.evaluate("refund_order", {"id": "o1"}, _runner())
    assert legacy.calls == 1  # no run_context kwarg was passed


def test_declaring_untrusted_tools_opts_in():
    spy = _CtxClient()
    guard = Guard(client=spy, mode="enforce", tenant="t", agent="a",
                  untrusted_tools={"read_public_issue"})
    guard.evaluate("refund_order", {"id": "o1"}, _runner())
    assert spy.contexts[-1] == {"untrusted_input": False}


def test_run_id_is_sent_when_set():
    spy = _CtxClient()
    guard = Guard(client=spy, mode="enforce", tenant="t", agent="a", run_id="run-7")
    guard.evaluate("refund_order", {"id": "o1"}, _runner())
    assert spy.contexts[-1] == {"untrusted_input": False, "run_id": "run-7"}


# ---- the taint itself -----------------------------------------------------

def test_untrusted_tool_taints_subsequent_calls_not_its_own():
    """Causal order: reading a public issue is not the problem. What the
    agent does afterwards is."""
    spy = _CtxClient()
    guard = Guard(client=spy, mode="enforce", tenant="t", agent="a",
                  untrusted_tools={"read_public_issue"})

    guard.evaluate("read_public_issue", {"id": "i1"}, _runner())
    assert spy.contexts[0] == {"untrusted_input": False}, "the untrusted read itself is clean"

    guard.evaluate("post_comment", {"id": "i1"}, _runner())
    assert spy.contexts[1] == {"untrusted_input": True}, "everything after it is not"


def test_taint_is_monotonic_within_a_run():
    spy = _CtxClient()
    guard = Guard(client=spy, mode="enforce", tenant="t", agent="a",
                  untrusted_tools={"fetch_url"})
    guard.evaluate("fetch_url", {"id": "u"}, _runner())
    for _ in range(3):
        guard.evaluate("refund_order", {"id": "o1"}, _runner())
    assert all(c["untrusted_input"] for c in spy.contexts[1:])


def test_manual_mark_taints_and_opts_in():
    spy = _CtxClient()
    guard = Guard(client=spy, mode="enforce", tenant="t", agent="a")
    assert guard.run_context() is None
    guard.mark_untrusted_input(source="webhook_body")
    guard.evaluate("refund_order", {"id": "o1"}, _runner())
    assert spy.contexts[-1] == {"untrusted_input": True}


def test_there_is_no_public_way_to_clear_taint():
    """The model must not be able to clear this. The guard exposes no
    untaint()/clear() and the property is read-only, so the only reset is
    start_run — an integrator action the model has no route to."""
    guard = Guard(mode="observe", agent="a", untrusted_tools={"fetch_url"})
    guard.mark_untrusted_input()
    assert guard.untrusted_input is True

    for name in ("clear", "untaint", "reset_taint", "clear_untrusted_input"):
        assert not hasattr(guard, name), f"Guard exposes {name}(): taint must be one-way"

    try:
        guard.untrusted_input = False
    except AttributeError:
        pass
    else:
        raise AssertionError("untrusted_input must not be settable")
    assert guard.untrusted_input is True


def test_start_run_clears_for_a_new_run():
    spy = _CtxClient()
    guard = Guard(client=spy, mode="enforce", tenant="t", agent="a",
                  untrusted_tools={"fetch_url"})
    guard.evaluate("fetch_url", {"id": "u"}, _runner())
    guard.evaluate("refund_order", {"id": "o1"}, _runner())
    assert spy.contexts[-1]["untrusted_input"] is True

    guard.start_run("run-2")
    guard.evaluate("refund_order", {"id": "o1"}, _runner())
    assert spy.contexts[-1] == {"untrusted_input": False, "run_id": "run-2"}


# ---- vote shape -----------------------------------------------------------

def test_vote_shape_taints_on_record_executed():
    """Vote-shape adapters run the tool outside the guard, so
    record_executed is the only place the guard learns it ran."""
    spy = _CtxClient()
    guard = Guard(client=spy, mode="enforce", tenant="t", agent="a",
                  untrusted_tools={"read_public_issue"})

    d = guard.decide_only("read_public_issue", {"id": "i1"})
    guard.record_executed("read_public_issue", {"id": "i1"}, d)

    guard.decide_only("post_comment", {"id": "i1"})
    assert spy.contexts[-1] == {"untrusted_input": True}


def test_observe_mode_taints_too():
    """Observe never blocks, but it must still track the run so a tenant
    flipping to enforce does not start from a false clean slate."""
    guard = Guard(mode="observe", agent="a", untrusted_tools={"read_public_issue"})
    guard.evaluate("read_public_issue", {"id": "i1"}, _runner())
    assert guard.untrusted_input is True
