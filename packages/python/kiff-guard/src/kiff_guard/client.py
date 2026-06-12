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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple
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


@dataclass
class DraftResult:
    """Returned by save_draft: the cloud's acknowledgement of the upserted
    domain draft. `valid` is True when the cloud parsed the YAML cleanly
    (a draft may be saved while still invalid mid-edit — `issues` lists the
    problems in that case)."""

    yaml: str
    updated_at: int = 0
    valid: bool = False
    issues: List[str] = field(default_factory=list)


@dataclass
class GuardToolObservation:
    """One observed tool, as pushed to KIFF Cloud (POST /v1/guard/observations).

    Mirrors the JS SDK's GuardToolObservation. Every field except `name` is
    optional and is omitted from the wire body when unset, so the push only
    ever carries what is genuinely known:

      name                — the tool's function name (observed).
      parameter_schema    — a JSON-schema-ish object of the argument keys
                            seen in real calls (no invented types/required).
      entity_arg/action/entity_type — the ToolMap binding, when the tool is
                            bound (real configuration, not inferred).
      required            — left unset by the catalog-derived path: which
                            args are required is human judgment, not observed.
      observed_call_count — how many times the tool was actually called.
    """

    name: str
    description: Optional[str] = None
    parameter_schema: Optional[Dict[str, Any]] = None
    entity_arg: Optional[str] = None
    action: Optional[str] = None
    entity_type: Optional[str] = None
    required: Optional[List[str]] = None
    observed_call_count: Optional[int] = None


@dataclass
class GuardObservation:
    """Returned by observe_guard: the cloud's stored observation for this
    tenant/project/environment/agent/workflow, echoing the tools it now
    knows about."""

    project: str = ""
    environment: str = ""
    agent_id: str = ""
    workflow: str = ""
    tools: List[GuardToolObservation] = field(default_factory=list)
    tenant_id: str = ""
    observed_at: str = ""
    updated_at: str = ""


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


class DraftSaver(Protocol):
    """Optional client capability for saving a derived domain draft to the
    KIFF Cloud draft store (PUT /v1/me/domain/draft), so an observe-mode
    draft shows up in the authoring UI. Implemented by HTTPClient."""

    def save_draft(self, yaml_text: str) -> DraftResult:
        ...


class ObservationPusher(Protocol):
    """Optional client capability for pushing the observed tool catalog to
    KIFF Cloud (POST /v1/guard/observations), so the cloud can derive a
    candidate domain from real traffic. Mirrors the JS SDK's observeGuard.
    Implemented by HTTPClient."""

    def observe_guard(
        self,
        agent_id: str,
        adapter: str,
        mode: str,
        tools: List["GuardToolObservation"],
        project: str = "",
        environment: str = "",
        workflow: str = "",
        sdk_version: str = "",
    ) -> GuardObservation:
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

    @property
    def tool_map(self) -> ToolMap:
        """The ToolMap this client decides against. Exposed (read-only) so
        Guard.observe_push can enrich observed tools with their bindings
        (action/entity_type/entity_arg) — the bindings live on the client
        because the client is what speaks decide."""
        return self._tool_map

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

    def observe_guard(
        self,
        agent_id: str,
        adapter: str,
        mode: str,
        tools: List[GuardToolObservation],
        project: str = "",
        environment: str = "",
        workflow: str = "",
        sdk_version: str = "",
    ) -> GuardObservation:
        """Push the observed tool catalog to KIFF Cloud
        (POST /v1/guard/observations). The cloud stores the observation and
        derives a candidate domain from it (action/entity bindings + the
        argument shapes seen). Call after the runtime has observed real
        tool traffic. Mirrors the JS SDK's observeGuard.

        Raises ConnectionError on transport failure or a non-2xx status,
        consistent with connect_guard / save_draft."""
        if not agent_id:
            raise ValueError("agent_id is required")
        if not adapter:
            raise ValueError("adapter is required")

        body: Dict[str, Any] = {
            "agent_id": agent_id,
            "adapter": adapter,
            "mode": mode,
            "tools": [_wire_tool_observation(t) for t in tools],
        }
        if project:
            body["project"] = project
        if environment:
            body["environment"] = environment
        if workflow:
            body["workflow"] = workflow
        if sdk_version:
            body["sdk_version"] = sdk_version

        status, payload = self._post("/v1/guard/observations", body)
        if status == 0:
            message = payload.get("message", "transport error") if payload else "transport error"
            raise ConnectionError(f"guard observe failed: {message}")
        if status < 200 or status >= 300:
            message = (
                payload.get("error", f"observations returned status {status}")
                if payload
                else f"observations returned status {status}"
            )
            raise ConnectionError(f"guard observe failed: {message}")

        return _observation_from_payload(payload.get("observation", payload) if payload else {})

    def save_draft(self, yaml_text: str) -> DraftResult:
        """Upsert a derived domain draft to the cloud draft store
        (PUT /v1/me/domain/draft). The tenant comes from the API key
        server-side; the draft is identified by that tenant. The cloud
        accepts the draft even if it is not yet valid (mid-edit), and
        reports parse issues in the result.

        Raises ConnectionError on transport failure or a non-2xx status,
        consistent with connect_guard."""
        if not yaml_text or not yaml_text.strip():
            raise ValueError("save_draft requires non-empty YAML")

        status, payload = self._put_yaml("/v1/me/domain/draft", yaml_text)
        if status == 0:
            message = payload.get("message", "transport error") if payload else "transport error"
            raise ConnectionError(f"save draft failed: {message}")
        if status < 200 or status >= 300:
            message = payload.get("error", f"save draft returned status {status}") if payload else f"save draft returned status {status}"
            raise ConnectionError(f"save draft failed: {message}")

        issues_raw = payload.get("issues") or []
        issues = [
            i.get("message", str(i)) if isinstance(i, dict) else str(i)
            for i in issues_raw
        ]
        return DraftResult(
            yaml=str(payload.get("yaml", yaml_text)),
            updated_at=int(payload.get("updated_at", 0) or 0),
            valid=(payload.get("parsed") is not None and not issues),
            issues=issues,
        )

    def _put_yaml(self, path: str, yaml_text: str) -> Tuple[int, Dict[str, Any]]:
        url = self._base + path
        data = yaml_text.encode("utf-8")
        req = urllib_request.Request(
            url,
            data=data,
            method="PUT",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/x-yaml",
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
            return 0, {"message": f"transport error: {exc.reason}"}
        payload: Dict[str, Any] = {}
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
        return status, payload

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


def _wire_tool_observation(tool: GuardToolObservation) -> Dict[str, Any]:
    """Render one GuardToolObservation to the wire shape, omitting unset
    fields so the push carries only what is known (parity with the JS
    SDK's wireToolObservation)."""
    body: Dict[str, Any] = {"name": tool.name}
    if tool.description:
        body["description"] = tool.description
    if tool.parameter_schema is not None:
        body["parameter_schema"] = tool.parameter_schema
    if tool.entity_arg:
        body["entity_arg"] = tool.entity_arg
    if tool.action:
        body["action"] = tool.action
    if tool.entity_type:
        body["entity_type"] = tool.entity_type
    if tool.required is not None:
        body["required"] = tool.required
    if tool.observed_call_count is not None:
        body["observed_call_count"] = tool.observed_call_count
    return body


def _observation_from_payload(payload: Dict[str, Any]) -> GuardObservation:
    """Parse the cloud's observation response back into a GuardObservation."""
    tools_raw = payload.get("tools") or []
    tools: List[GuardToolObservation] = []
    for t in tools_raw:
        if not isinstance(t, dict):
            continue
        required = t.get("required")
        tools.append(
            GuardToolObservation(
                name=str(t.get("name", "")),
                description=(str(t["description"]) if t.get("description") else None),
                parameter_schema=(t["parameter_schema"] if isinstance(t.get("parameter_schema"), dict) else None),
                entity_arg=(str(t["entity_arg"]) if t.get("entity_arg") else None),
                action=(str(t["action"]) if t.get("action") else None),
                entity_type=(str(t["entity_type"]) if t.get("entity_type") else None),
                required=([str(x) for x in required] if isinstance(required, list) else None),
                observed_call_count=(int(t["observed_call_count"]) if t.get("observed_call_count") is not None else None),
            )
        )
    return GuardObservation(
        project=str(payload.get("project", "")),
        environment=str(payload.get("environment", "")),
        agent_id=str(payload.get("agent_id", "")),
        workflow=str(payload.get("workflow", "")),
        tools=tools,
        tenant_id=str(payload.get("tenant_id", "")),
        observed_at=str(payload.get("observed_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )
