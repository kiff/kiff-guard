"""guard — the framework-agnostic core.

`Guard` knows nothing about any agent framework. It exposes three
primitives adapters build on, depending on the framework's control shape:

  observe(tool, args)            — learn + record an "observed" receipt.
                                   No decision, no run. (observe mode)
  decide_only(tool, args)        — learn + call KIFF decide and return the
                                   Decision. Does NOT run the tool and does
                                   NOT record — the adapter records exactly
                                   one receipt via record_executed (allowed)
                                   or record_withheld (withheld). (enforce)
  record_executed / record_withheld — the vote-shape adapter's single
                                   audit write, so one receipt per call.
  evaluate(tool, args, run)      — convenience for middleware frameworks
                                   that let the guard run the tool itself:
                                   observe-and-run, or decide-and-run-or-Hold
                                   (records one receipt internally).

Two adapter shapes use these differently:

  - Middleware / hook frameworks (Agno tool_hooks, Pydantic AI, …) let
    the guard run the tool, so they call `evaluate(tool, args, run=...)`.
  - Inverted-control / approval-native frameworks (Hermes pre_tool_call,
    LangGraph interrupt, OpenAI needs_approval, …) run the tool
    themselves after the hook returns; the hook only votes allow/block.
    They call `observe()` (observe mode) or `decide_only()` (enforce) and
    act on the returned Decision — never the run callback.

observe mode is decide-independent (#244): it works with no client and
no tenant, so a fresh user gets a real audit trail before they have any
KIFF account. The guard logic lives here, once; adapters add none.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from .catalog import Catalog
from .client import Client
from .decision import Decision, Hold, Receipt


class Guard:
    """One Guard instance governs the tools of one logical agent. Share a
    Catalog + ledger across guards on the same tenant to get one tower,
    one learned surface, one audit log over every agent."""

    def __init__(
        self,
        client: Optional[Client] = None,
        tenant: str = "",
        agent: Optional[str] = None,
        mode: str = "observe",
        catalog: Optional[Catalog] = None,
        ledger: Optional[List[Receipt]] = None,
        run_id: str = "",
        untrusted_tools: Iterable[str] = (),
        sensitive_tools: Iterable[str] = (),
    ):
        if mode not in ("observe", "enforce"):
            raise ValueError("mode must be 'observe' or 'enforce'")
        # enforce calls decide -> needs a client. observe is decide-
        # independent and works with no client at all (#244).
        if mode == "enforce" and client is None:
            raise ValueError("enforce mode requires a client")
        self.client = client
        self.tenant = tenant
        self.agent = agent if agent is not None else "agent"
        self._agent_explicit = agent is not None
        self.mode = mode
        self.catalog = catalog if catalog is not None else Catalog()
        self.receipts: List[Receipt] = ledger if ledger is not None else []
        # Run context (kiff-cloud RFC 039). Asserted by this guard — which
        # is trusted integrator code — and never by the model.
        #
        # `untrusted_tools` names the tools whose *results* bring content
        # from somewhere the agent's instructions do not come from: a
        # fetched page, a third-party ticket, a document, a tool reaching
        # outside this run's remit. The integrator declares the set up
        # front; the guard applies it mechanically by tool name. The model
        # can choose to call such a tool, and calling it can only ever ADD
        # taint, never remove it.
        self.run_id = run_id
        self.untrusted_tools = frozenset(untrusted_tools)
        self._untrusted_input = False
        # `sensitive_tools` names the tools whose results bring content
        # the agent should not be free to forward: a private repository,
        # a secret store, a record outside the run's remit. Same
        # mechanics as untrusted_tools and a different question — that
        # set asks where instructions could have come from, this one
        # asks what the run has seen that it must not leak.
        #
        # Together they describe the chain the control exists to break:
        # untrusted content arrives, something sensitive is read, and
        # something public is written. An action can gate on the
        # conjunction (`on_untrusted_sensitive_read`) instead of on
        # taint alone, which matters because taint alone does not
        # discriminate on an agent whose work begins by reading a public
        # issue — measured at 90 of 90 benign runs tainted.
        self.sensitive_tools = frozenset(sensitive_tools)
        self._sensitive_read = False
        # Tracked separately from _run_context_on, because asserting
        # `sensitive_read: false` is a claim this guard can only make if
        # it is actually watching for sensitive reads. A guard that
        # names no sensitive tools and never calls mark_sensitive_read
        # omits the key entirely, and the cloud fails closed on an
        # action that gates on it. Sending a false it did not establish
        # would convert that fail-closed into a fail-open — the one
        # mistake this field is shaped to prevent.
        self._sensitive_tracking_on = bool(self.sensitive_tools)
        # Run context is opt-in, and stays off until the integrator asks
        # for it by naming untrusted tools, setting a run id, or calling
        # mark_untrusted_input/start_run. A guard that never opts in sends
        # no run_context field and works with any Client implementation
        # written before RFC 039 — including custom ones outside this
        # repo, which is why this is a flag rather than an always-on
        # keyword argument.
        #
        # Opting out is not a way to dodge the control: an action that
        # declares a run-context dependency and receives no assertion
        # fails closed cloud-side. Sending nothing means "I have not
        # established anything", not "this run is clean".
        self._run_context_on = (
            bool(run_id) or bool(self.untrusted_tools) or bool(self.sensitive_tools)
        )

    # ---- run context (kiff-cloud RFC 039) -------------------------------
    #
    # The runtime has no independent account of what happened in a run:
    # the only proposal fields that say *why* an action is proposed are
    # written by the model. These methods are how a harness supplies that
    # missing fact, from trusted code.
    #
    # Deliberately one-way. There is no clear()/untaint() method, because
    # the whole point is that nothing the model can influence may reset
    # it. A new run gets a new run context via `start_run`, which is an
    # explicit act by the integrator, not something a tool result can do.

    def mark_untrusted_input(self, source: str = "") -> None:
        """Assert that content from an untrusted source has entered this
        run. Monotonic: once asserted it holds until `start_run`.

        Call this where the untrusted content actually arrives. The
        `untrusted_tools` set does it automatically for tools you named up
        front; this is the manual path for everything else (a webhook body,
        a user-pasted document, a file read outside the tool layer)."""
        self._untrusted_input = True
        self._run_context_on = True
        if source:
            self.catalog.record(self.agent, f"kiff.untrusted_input:{source}", {})

    def mark_sensitive_read(self, source: str = "") -> None:
        """Assert that this run has been served sensitive content.
        Monotonic, like taint: once asserted it holds until `start_run`.

        Call it where the sensitive content actually arrives. The
        `sensitive_tools` set does it automatically for tools named up
        front; this is the manual path for everything else.

        Calling this also turns on the tracking flag, because a guard
        that reports a sensitive read is by definition watching for
        them."""
        self._sensitive_read = True
        self._sensitive_tracking_on = True
        self._run_context_on = True
        if source:
            self.catalog.record(self.agent, f"kiff.sensitive_read:{source}", {})

    def start_run(self, run_id: str = "") -> None:
        """Begin a new run: clears the run's asserted facts and sets the
        run id. Call it between independent tasks on a long-lived
        guard. It is an integrator action by construction — the model has
        no route to it — which is what makes clearing taint here safe and
        clearing it anywhere else not.

        Clears the facts, not the tracking: a guard that was watching for
        sensitive reads before the run boundary is still watching after
        it, so `sensitive_read: false` on the new run is a claim it is
        still entitled to make."""
        self.run_id = run_id
        self._untrusted_input = False
        self._sensitive_read = False
        self._run_context_on = True

    @property
    def untrusted_input(self) -> bool:
        """Whether this run has been marked as having consumed untrusted
        input. Read-only on purpose: see mark_untrusted_input."""
        return self._untrusted_input

    @property
    def sensitive_read(self) -> bool:
        """Whether this run has been marked as having read sensitive
        content. Read-only on purpose: see mark_sensitive_read."""
        return self._sensitive_read

    def run_context(self) -> Optional[Dict[str, Any]]:
        """The run context to send with a decision.

        Always includes `untrusted_input`, including when False. An
        explicit clean assertion and no assertion at all are different
        facts to the runtime: a declaring action fails closed on the
        second, because absence is not evidence of a clean run. A guard
        that sends this dict is making the first claim, and is
        responsible for it being true.

        None when this guard never opted in, so the decide call is made
        without the field and any pre-RFC-039 Client keeps working."""
        if not self._run_context_on:
            return None
        ctx: Dict[str, Any] = {"untrusted_input": self._untrusted_input}
        # Omitted unless this guard actually tracks sensitive reads. The
        # cloud reads an absent key as "unasserted" and refuses an action
        # that depends on it; it would read `false` as "no sensitive read
        # happened" and allow. Only one of those is true for a guard that
        # was never watching.
        if self._sensitive_tracking_on:
            ctx["sensitive_read"] = self._sensitive_read
        if self.run_id:
            ctx["run_id"] = self.run_id
        return ctx

    def _decide(self, tool: str, args: Dict[str, Any]) -> Decision:
        """Call the client, passing run context only when this guard has
        any. Keeps the Client contract unchanged for callers that never
        opted in."""
        ctx = self.run_context()
        if ctx is None:
            return self.client.decide(self.tenant, self.agent, tool, args)
        return self.client.decide(self.tenant, self.agent, tool, args, run_context=ctx)

    def _note_untrusted_tool(self, tool: str) -> None:
        """Apply the declared untrusted-tool and sensitive-tool sets.
        Called after a tool has run, so the facts land on everything the
        agent does *next* — the causal order that matters. Reading a
        public issue is not itself the problem, and neither is reading a
        private file; what the agent does afterwards is."""
        if tool in self.untrusted_tools:
            self._untrusted_input = True
        if tool in self.sensitive_tools:
            self._sensitive_read = True

    def observe(self, tool: str, args: Dict[str, Any]) -> None:
        """Record an observed receipt and learn the catalog. No decision,
        no run. The primitive for inverted-control adapters in observe
        mode (and the body of evaluate's observe branch).

        Decide-independent (#244): never calls KIFF. Valid with no client
        and no tenant."""
        self.catalog.record(self.agent, tool, args)
        self._record_observed(tool, args)
        self._note_untrusted_tool(tool)

    def decide_only(self, tool: str, args: Dict[str, Any]) -> Decision:
        """Ask KIFF to decide and return the Decision WITHOUT running the
        tool and WITHOUT recording a receipt. The primitive for
        inverted-control adapters in enforce mode: the framework runs or
        skips the tool based on `decision.withheld`, then the adapter
        records exactly one receipt via `record_executed` (allowed) or
        `record_withheld` (withheld).

        Why no receipt here: the decision and the execution are two
        moments for a vote-shape adapter, but the *audit* must be one row
        per tool call — same shape as the middleware path. So recording
        is the adapter's explicit, single call, never a side effect of
        deciding. (Fixes the double-receipt issue: #239 / #250 review.)"""
        if self.client is None:
            raise ValueError("decide_only requires a client (enforce mode)")
        self.catalog.record(self.agent, tool, args)
        return self._decide(tool, args)

    def evaluate(self, tool: str, args: Dict[str, Any], run: Callable[[], Any]) -> Any:
        """Convenience entry point for middleware frameworks that let the
        guard run the tool. `run` is a zero-arg callable that executes the
        tool (the adapter closes over the framework's continuation).
        Returns the tool result, or raises Hold in enforce mode when KIFF
        withholds clearance.

        Implemented on top of the observe / decide primitives so there is
        one source of truth for the observe/enforce + audit logic."""
        # Learn from every call, in both modes — integration is discovery.
        self.catalog.record(self.agent, tool, args)

        if self.mode == "observe":
            result = run()
            self._record_observed(tool, args)
            self._note_untrusted_tool(tool)
            return result

        decision = self._decide(tool, args)
        if decision.allowed:
            result = run()
            self._record_governed(tool, args, decision, executed=True)
            self._note_untrusted_tool(tool)
            return result

        self._record_governed(tool, args, decision, executed=False)
        raise Hold(decision)

    def record_executed(self, tool: str, args: Dict[str, Any], decision: Decision) -> None:
        """Record exactly one governed receipt for an action the framework
        executed after an allowed `decide_only`. The vote-shape adapter's
        single audit write on the allowed path."""
        self._record_governed(tool, args, decision, executed=True)
        # Vote shape runs the tool outside the guard, so this is the only
        # point where the guard learns it actually ran. Without it, a
        # vote-shape adapter would never taint and every declared
        # untrusted tool would be invisible to run context.
        self._note_untrusted_tool(tool)

    def record_withheld(self, tool: str, args: Dict[str, Any], decision: Decision) -> None:
        """Record exactly one governed receipt for an action KIFF withheld
        (the framework skipped it). The vote-shape adapter's single audit
        write on the withheld path. Pairs with `record_executed` so a
        vote-shape adapter emits one receipt per call, matching the
        middleware path."""
        self._record_governed(tool, args, decision, executed=False)

    def connect(
        self,
        adapter: str,
        project: str = "",
        environment: str = "",
        workflow: str = "",
        sdk_version: str = "",
    ) -> Any:
        """Opt into KIFF Cloud runtime discovery. Call this after creating
        the guard to register this runtime in the dashboard. Separate from
        observe/enforce so zero-config audit stays local unless the caller
        explicitly connects.

        Requires a client that implements GuardConnector (HTTPClient does).
        Returns the GuardConnection from the cloud."""
        from .client import GuardConnector

        if self.client is None:
            raise ValueError("connect requires a client")
        if not hasattr(self.client, "connect_guard"):
            raise ValueError("connect requires a client with connect_guard (HTTPClient)")
        connection = self.client.connect_guard(  # type: ignore[union-attr]
            agent_id=self.agent if self._agent_explicit else "",
            adapter=adapter,
            mode=self.mode,
            project=project,
            environment=environment,
            workflow=workflow,
            sdk_version=sdk_version,
        )
        if not connection.agent_id:
            raise ValueError("guard connect returned no agent_id")
        self.agent = connection.agent_id
        return connection

    def save_draft(self, domain_name: str) -> Any:
        """Save the domain draft derived from observed traffic to the KIFF
        Cloud draft store, so it appears in the authoring UI. Renders the
        learned catalog with export_yaml and PUTs it.

        This is the credentialed half of instrument-first authoring; the
        credential-less fallback is to call export_yaml yourself and paste
        the result. Separate from observe/enforce so zero-config audit
        stays local unless the caller explicitly saves.

        Requires a client that implements DraftSaver (HTTPClient does).
        Returns the DraftResult from the cloud."""
        from .draft import export_yaml

        if self.client is None:
            raise ValueError("save_draft requires a client")
        if not hasattr(self.client, "save_draft"):
            raise ValueError("save_draft requires a client with save_draft (HTTPClient)")
        yaml_text = export_yaml(domain_name, self.catalog)
        return self.client.save_draft(yaml_text)  # type: ignore[union-attr]

    def observe_push(
        self,
        adapter: str,
        project: str = "",
        environment: str = "",
        workflow: str = "",
        sdk_version: str = "",
    ) -> Any:
        """Push the observed tool catalog to KIFF Cloud so it can derive a
        candidate domain from real traffic (POST /v1/guard/observations).
        Parallel to connect() / save_draft(): separate from observe/enforce
        so zero-config audit stays local unless the caller explicitly pushes.

        Turns the learned Catalog + the client's ToolMap bindings into tool
        observations. It only reports what is genuinely known:

          - name                — the observed tool.
          - parameter_schema    — the argument keys seen in real calls, as
                                  object properties (no invented types).
          - action/entity_type/entity_arg — from the ToolMap binding, when
                                  the tool is bound (real configuration).
          - observed_call_count — the real number of observed calls.

        It deliberately does NOT set `required`, a risk level, a state, or
        any threshold: those are human judgment, never inferred from
        traffic. Unbound/unmapped tools are still reported (name + observed
        args), carrying no action binding.

        Requires a client that implements ObservationPusher (HTTPClient does).
        Returns the GuardObservation echoed by the cloud."""
        from .client import GuardToolObservation

        if self.client is None:
            raise ValueError("observe_push requires a client")
        if not hasattr(self.client, "observe_guard"):
            raise ValueError("observe_push requires a client with observe_guard (HTTPClient)")

        tool_map = getattr(self.client, "tool_map", None)
        tools: List[GuardToolObservation] = []
        for name in sorted(self.catalog.tools):
            arg_keys = sorted(self.catalog.tools[name])
            binding = tool_map.get(name) if tool_map is not None else None
            count = self.catalog.counts.get(name, 0)
            tools.append(
                GuardToolObservation(
                    name=name,
                    parameter_schema=(
                        {"type": "object", "properties": {k: {} for k in arg_keys}}
                        if arg_keys
                        else None
                    ),
                    entity_arg=(binding.entity_arg if binding else None),
                    action=(binding.action if binding else None),
                    entity_type=(binding.entity_type if binding else None),
                    observed_call_count=(count if count else None),
                )
            )

        return self.client.observe_guard(  # type: ignore[union-attr]
            agent_id=self.agent,
            adapter=adapter,
            mode=self.mode,
            tools=tools,
            project=project,
            environment=environment,
            workflow=workflow,
            sdk_version=sdk_version,
        )

    # --- audit ---------------------------------------------------------

    def _record_observed(self, tool: str, args: Dict[str, Any]) -> None:
        self.receipts.append(
            Receipt(
                ts=time.time(), agent=self.agent, tool=tool, args=dict(args),
                outcome="observed", reason="observe mode: recorded, not governed",
                executed=True, state="observed",
            )
        )

    def _record_governed(self, tool: str, args: Dict[str, Any], decision: Decision, executed: bool) -> None:
        self.receipts.append(
            Receipt(
                ts=time.time(), agent=self.agent, tool=tool, args=dict(args),
                outcome=decision.outcome, reason=decision.reason,
                executed=executed, state="governed", proposal_id=decision.proposal_id,
            )
        )
