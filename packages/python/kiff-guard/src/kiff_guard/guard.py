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
from typing import Any, Callable, Dict, List, Optional

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
        agent: str = "agent",
        mode: str = "observe",
        catalog: Optional[Catalog] = None,
        ledger: Optional[List[Receipt]] = None,
    ):
        if mode not in ("observe", "enforce"):
            raise ValueError("mode must be 'observe' or 'enforce'")
        # enforce calls decide -> needs a client. observe is decide-
        # independent and works with no client at all (#244).
        if mode == "enforce" and client is None:
            raise ValueError("enforce mode requires a client")
        self.client = client
        self.tenant = tenant
        self.agent = agent
        self.mode = mode
        self.catalog = catalog if catalog is not None else Catalog()
        self.receipts: List[Receipt] = ledger if ledger is not None else []

    def observe(self, tool: str, args: Dict[str, Any]) -> None:
        """Record an observed receipt and learn the catalog. No decision,
        no run. The primitive for inverted-control adapters in observe
        mode (and the body of evaluate's observe branch).

        Decide-independent (#244): never calls KIFF. Valid with no client
        and no tenant."""
        self.catalog.record(self.agent, tool, args)
        self._record_observed(tool, args)

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
        return self.client.decide(self.tenant, self.agent, tool, args)

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
            return result

        decision = self.client.decide(self.tenant, self.agent, tool, args)
        if decision.allowed:
            result = run()
            self._record_governed(tool, args, decision, executed=True)
            return result

        self._record_governed(tool, args, decision, executed=False)
        raise Hold(decision)

    def record_executed(self, tool: str, args: Dict[str, Any], decision: Decision) -> None:
        """Record exactly one governed receipt for an action the framework
        executed after an allowed `decide_only`. The vote-shape adapter's
        single audit write on the allowed path."""
        self._record_governed(tool, args, decision, executed=True)

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
        return self.client.connect_guard(  # type: ignore[union-attr]
            agent_id=self.agent,
            adapter=adapter,
            mode=self.mode,
            project=project,
            environment=environment,
            workflow=workflow,
            sdk_version=sdk_version,
        )

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
