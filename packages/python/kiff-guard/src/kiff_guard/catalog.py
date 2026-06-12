"""Catalog — the action surface derived from observed agent traffic.

The honest half of instrument-first authoring: tool names and argument
shapes can be *derived* from real calls. Risk level, the state machine,
and approval policy cannot — they are human judgment, left as TODO in the
draft (see draft.py). We never infer what we cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Set


@dataclass
class Catalog:
    """One entry per distinct tool, accumulating the argument keys seen
    across calls, plus the set of agents observed. Shared across every
    guard on one tenant: one tower, one learned surface.

    `counts` is the only quantitative fact we record — how many times each
    tool was observed. It is a count of real calls, not a threshold or a
    limit: the guard never infers policy from it (risk/state/approval stay
    human judgment). It exists so an observation push can report a truthful
    observed_call_count."""

    tools: Dict[str, Set[str]] = field(default_factory=dict)
    agents: Set[str] = field(default_factory=set)
    counts: Dict[str, int] = field(default_factory=dict)

    def record(self, agent: str, tool: str, args: Dict[str, Any]) -> None:
        self.agents.add(agent)
        self.tools.setdefault(tool, set()).update(args.keys())
        self.counts[tool] = self.counts.get(tool, 0) + 1
