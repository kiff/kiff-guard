"""kiff-guard — drop-in KIFF clearance for any agent's tool calls.

Quickstart (zero-config audit, no KIFF account needed):

    from kiff_guard import Guard
    from kiff_guard.adapters.agno import agno_hook

    guard = Guard(mode="observe")
    agent = Agent(model=..., tools=[...], tool_hooks=[agno_hook(guard)])
    # run the agent; then inspect guard.receipts and
    # kiff_guard.draft.export_yaml(name, guard.catalog)

Enforce (once you have a tenant + an active domain):

    from kiff_guard import Guard, HTTPClient, ToolMap
    client = HTTPClient(api_key="kiff_live_...", tool_map=ToolMap().bind(
        "refund_order", action="REFUND_ORDER", entity_type="Order", entity_arg="order_id"))
    guard = Guard(client=client, tenant="...", agent="support", mode="enforce")
"""

from __future__ import annotations

from .catalog import Catalog
from .client import (
    Client,
    DraftResult,
    DraftSaver,
    GuardConnection,
    GuardConnector,
    HTTPClient,
    ToolBinding,
    ToolMap,
)
from .decision import Decision, Hold, Receipt
from .draft import export_yaml
from .guard import Guard

__all__ = [
    "Guard",
    "Decision",
    "Hold",
    "Receipt",
    "Catalog",
    "Client",
    "DraftResult",
    "DraftSaver",
    "GuardConnection",
    "GuardConnector",
    "HTTPClient",
    "ToolMap",
    "ToolBinding",
    "export_yaml",
]

__version__ = "0.1.0"
