"""client — the seam between the guard and KIFF.

`HTTPClient` speaks the real KIFF decide protocol, verified against the
live api.kiff.dev decide endpoint:

    POST /v1/proposals/decide
    Authorization: Bearer kiff_live_<tenant>_<random>
    body: {entity_id, entity_type, action_name, actor_id, parameters,
           reasoning_summary?, confidence?, id?}
    -> {proposal_id, outcome, reasons[], message}

`ToolMap` is the load-bearing bridge: an agent tool call gives a function
name + a flat args dict, but decide needs action_name + entity_id +
entity_type. ToolMap binds each tool to its action and names the arg that
carries the entity id.

Roles are deliberately NOT sent: the decide handler refuses caller-
asserted roles (a caller must not self-grant the authority that makes its
own action allowed). actor_id is sent; the API key's roles govern
server-side. The guard therefore cannot weaken the trust boundary.

stdlib-only (urllib) — zero required runtime deps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

from .decision import Decision, INVALID


@dataclass
class GuardConnection:
    """Returned by connect_guard: the cloud's acknowledgement that this
    runtime is registered and will appear in the dashboard."""

    runtime_id: str
    heartbeat_interval: str
    tenant_id: str
    project: str
    environment: str
    agent_id: str
    workflow: str
    adapter: str
    mode: str
    sdk_version: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    seen_count: int = 0


class Client(Protocol):
    """What the guard needs from a decider. Implemented by HTTPClient;
    tests can pass any object with this method."""

    def decide(self, tenant: str, agent: str, tool: str, args: Dict[str, Any]) -> Decision:
        ...


class GuardConnector(Protocol):
    """Optional client capability for registering a live guard runtime
    with KIFF Cloud. Mirrors the TS SDK's GuardConnector interface."""

    def connect_guard(
        self,
        agent_id: str,
        adapter: str,
        mode: str,
        project: str = "",
        environment: str = "",
        workflow: str = "",
        sdk_version: str = "",
    ) -> GuardConnection:
        ...


@dataclass
class ToolBinding:
    """How one tool maps onto a KIFF action contract.

    action       — the action_name the tenant's domain declares.
    entity_type  — the entity_type the action operates on.
    entity_arg   — the tool argument carrying the entity id (the guard
                   reads args[entity_arg] and excludes it from parameters).
    """

    action: str
    entity_type: str
    entity_arg: str


class ToolMap:
    """tool name -> ToolBinding. Unmapped tools are 'no KIFF opinion':
    the guard clears + audits them, so attaching the guard never breaks a
    tool the user has not classified yet (observe-friendly default)."""

    def __init__(self, bindings: Optional[Dict[str, ToolBinding]] = None):
        self._bindings = dict(bindings or {})

    def bind(self, tool: str, action: str, entity_type: str, entity_arg: str) -> "ToolMap":
        self._bindings[tool] = ToolBinding(action, entity_type, entity_arg)
        return self

    def get(self, tool: str) -> Optional[ToolBinding]:
        return self._bindings.get(tool)


class HTTPClient:
    """Real client for the cloud decide endpoint."""

    def __init__(
        self,
        api_key: str,
        tool_map: ToolMap,
        base_url: str = "https://api.kiff.dev",
        timeout: float = 10.0,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._tool_map = tool_map
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def decide(self, tenant: str, agent: str, tool: str, args: Dict[str, Any]) -> Decision:
        binding = self._tool_map.get(tool)

        # Unmapped tool: no action to propose. Cleared + audited.
        if binding is None:
            return Decision(outcome="allowed", reason=f"{tool} unmapped; cleared and audited")

        entity_id = args.get(binding.entity_arg)
        if entity_id is None:
            return Decision(
                outcome=INVALID,
                reason=f"tool {tool}: entity arg {binding.entity_arg!r} missing from call",
            )

        body: Dict[str, Any] = {
            "entity_id": str(entity_id),
            "entity_type": binding.entity_type,
            "action_name": binding.action,
            "actor_id": agent,
            "parameters": {k: v for k, v in args.items() if k != binding.entity_arg},
        }

        status, payload = self._post("/v1/proposals/decide", body)
        outcome = str(payload.get("outcome", "")) if payload else ""
        if not outcome:
            # Never fail open silently: no outcome -> invalid, and the
            # guard's enforce path Holds on any non-allowed outcome.
            return Decision(outcome=INVALID, reason=f"decide returned status {status} with no outcome")

        reasons = payload.get("reasons") or []
        message = str(payload.get("message", ""))
        reason = message or (", ".join(reasons) if reasons else outcome)
        return Decision(outcome=outcome, reason=reason, proposal_id=str(payload.get("proposal_id", "")))

    def connect_guard(
        self,
        agent_id: str,
        adapter: str,
        mode: str,
        project: str = "",
        environment: str = "",
        workflow: str = "",
        sdk_version: str = "",
    ) -> GuardConnection:
        """Register this guard runtime with KIFF Cloud. The runtime will
        appear in the dashboard grouped by project/environment/agent/workflow.
        Call periodically (every 60s) as a heartbeat."""
        body: Dict[str, Any] = {
            "agent_id": agent_id,
            "adapter": adapter,
            "mode": mode,
        }
        if project:
            body["project"] = project
        if environment:
            body["environment"] = environment
        if workflow:
            body["workflow"] = workflow
        if sdk_version:
            body["sdk_version"] = sdk_version

        status, payload = self._post("/v1/guard/connect", body)
        if status == 0:
            message = payload.get("message", "transport error") if payload else "transport error"
            raise ConnectionError(f"guard connect failed: {message}")
        if status < 200 or status >= 300:
            message = payload.get("error", f"connect returned status {status}") if payload else f"connect returned status {status}"
            raise ConnectionError(f"guard connect failed: {message}")

        return GuardConnection(
            runtime_id=str(payload.get("runtime_id", "")),
            heartbeat_interval=str(payload.get("heartbeat_interval", "60s")),
            tenant_id=str(payload.get("tenant_id", "")),
            project=str(payload.get("project", "")),
            environment=str(payload.get("environment", "")),
            agent_id=str(payload.get("agent_id", "")),
            workflow=str(payload.get("workflow", "")),
            adapter=str(payload.get("adapter", "")),
            mode=str(payload.get("mode", "")),
            sdk_version=str(payload.get("sdk_version", "")),
            first_seen_at=str(payload.get("first_seen_at", "")),
            last_seen_at=str(payload.get("last_seen_at", "")),
            seen_count=int(payload.get("seen_count", 0)),
        )

    def _post(self, path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        url = self._base + path
        data = json.dumps(body).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8")
        except urllib_error.URLError as exc:
            return 0, {"outcome": "", "message": f"transport error: {exc.reason}"}
        payload: Dict[str, Any] = {}
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
        return status, payload
