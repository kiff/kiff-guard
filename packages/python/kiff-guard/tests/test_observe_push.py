"""Guard.observe_push + HTTPClient.observe_guard — pushing the observed
tool catalog to KIFF Cloud (POST /v1/guard/observations).

Offline: the Guard path uses a stub ObservationPusher that captures the
tool list, and the HTTPClient path monkeypatches the transport (_post) to
script cloud responses and capture the wire body. No cloud, no network.

What these pin:
  - the wire payload shape matches the contract (snake_case, unset fields
    omitted);
  - ToolMap-bound fields (action / entity_type / entity_arg) survive the
    catalog -> observation derivation;
  - the derivation invents nothing: no `required`, no risk/state/approval/
    threshold, no description — only observed facts + real bindings.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import (  # noqa: E402
    GuardObservation,
    GuardToolObservation,
    Guard,
    HTTPClient,
    ToolMap,
)


class _StubPusher:
    """A client implementing the ObservationPusher shape + a tool_map, so
    Guard.observe_push can derive bindings. Captures the derived tools."""

    def __init__(self, tool_map: ToolMap):
        self.tool_map = tool_map
        self.calls = []

    def observe_guard(self, agent_id, adapter, mode, tools, project="",
                      environment="", workflow="", sdk_version=""):
        self.calls.append({
            "agent_id": agent_id, "adapter": adapter, "mode": mode,
            "tools": tools, "project": project, "environment": environment,
            "workflow": workflow, "sdk_version": sdk_version,
        })
        return GuardObservation(agent_id=agent_id, project=project,
                                environment=environment, workflow=workflow, tools=tools)

    def decide(self, *a, **k):  # present so Guard accepts it as a Client
        ...


class _BareClient:
    def decide(self, *a, **k):
        ...


def _bound_map() -> ToolMap:
    return (
        ToolMap()
        .bind("contact_customer", action="CONTACT_CUSTOMER",
              entity_type="Customer", entity_arg="customer_id")
        .bind("offer_product", action="OFFER_PRODUCT",
              entity_type="Customer", entity_arg="customer_id")
    )


# --- Guard.observe_push guards --------------------------------------------

def test_observe_push_requires_a_client():
    guard = Guard(mode="observe", agent="a")  # no client
    with pytest.raises(ValueError, match="requires a client"):
        guard.observe_push(adapter="agno")


def test_observe_push_requires_client_with_observe_guard():
    guard = Guard(client=_BareClient(), tenant="t", agent="a", mode="observe")
    with pytest.raises(ValueError, match="observe_guard"):
        guard.observe_push(adapter="agno")


# --- Guard.observe_push derivation ----------------------------------------

def test_observe_push_preserves_toolmap_bindings_and_real_signatures():
    tmap = _bound_map()
    pusher = _StubPusher(tmap)
    guard = Guard(client=pusher, tenant="cookbook", agent="customer-ops-team", mode="enforce")

    # Real observed calls (the shapes the tools are actually called with).
    guard.catalog.record("customer-ops-team", "contact_customer",
                          {"customer_id": "c1", "channel": "sms", "message": "hi"})
    guard.catalog.record("customer-ops-team", "contact_customer",
                          {"customer_id": "c1", "channel": "email", "message": "again"})
    guard.catalog.record("customer-ops-team", "offer_product",
                          {"customer_id": "c1", "product": "loan-topup"})

    obs = guard.observe_push(adapter="agno", project="cookbook",
                             environment="aws", workflow="vulnerability-escalation",
                             sdk_version="0.1.0")

    assert len(pusher.calls) == 1
    call = pusher.calls[0]
    assert call["agent_id"] == "customer-ops-team"
    assert call["adapter"] == "agno"
    assert call["mode"] == "enforce"
    assert call["project"] == "cookbook" and call["environment"] == "aws"
    assert call["workflow"] == "vulnerability-escalation"

    by_name = {t.name: t for t in call["tools"]}
    assert set(by_name) == {"contact_customer", "offer_product"}

    contact = by_name["contact_customer"]
    # ToolMap binding survived.
    assert contact.action == "CONTACT_CUSTOMER"
    assert contact.entity_type == "Customer"
    assert contact.entity_arg == "customer_id"
    # parameter_schema reflects the REAL observed argument keys (union).
    assert contact.parameter_schema["type"] == "object"
    assert set(contact.parameter_schema["properties"]) == {"customer_id", "channel", "message"}
    # observed_call_count is the real number of calls (2 contacts).
    assert contact.observed_call_count == 2

    offer = by_name["offer_product"]
    assert offer.action == "OFFER_PRODUCT"
    assert set(offer.parameter_schema["properties"]) == {"customer_id", "product"}
    assert offer.observed_call_count == 1

    # Returned observation echoes the tools.
    assert {t.name for t in obs.tools} == {"contact_customer", "offer_product"}


def test_observe_push_invents_no_thresholds_states_or_required():
    tmap = _bound_map()
    pusher = _StubPusher(tmap)
    guard = Guard(client=pusher, tenant="t", agent="a", mode="enforce")
    guard.catalog.record("a", "contact_customer", {"customer_id": "c1", "channel": "sms"})

    guard.observe_push(adapter="agno")

    tool = pusher.calls[0]["tools"][0]
    # Nothing inferred: no required list, no description, and the dataclass
    # carries no risk/state/approval/threshold fields at all.
    assert tool.required is None
    assert tool.description is None
    field_names = set(GuardToolObservation.__dataclass_fields__)
    for forbidden in ("risk", "state", "states", "threshold", "approval", "limit"):
        assert forbidden not in field_names


def test_observe_push_reports_unmapped_tool_without_binding():
    tmap = _bound_map()  # send_email is NOT bound
    pusher = _StubPusher(tmap)
    guard = Guard(client=pusher, tenant="t", agent="a", mode="observe")
    guard.catalog.record("a", "send_email", {"to": "x@y.z"})

    guard.observe_push(adapter="agno")

    tool = {t.name: t for t in pusher.calls[0]["tools"]}["send_email"]
    assert tool.action is None and tool.entity_type is None and tool.entity_arg is None
    assert set(tool.parameter_schema["properties"]) == {"to"}
    assert tool.observed_call_count == 1


# --- HTTPClient.observe_guard wire shape + errors -------------------------

def _client():
    return HTTPClient(api_key="kiff_live_t_x", tool_map=_bound_map(), base_url="https://api.example")


def test_http_observe_guard_requires_agent_and_adapter():
    c = _client()
    with pytest.raises(ValueError, match="agent_id"):
        c.observe_guard(agent_id="", adapter="agno", mode="enforce", tools=[])
    with pytest.raises(ValueError, match="adapter"):
        c.observe_guard(agent_id="a", adapter="", mode="enforce", tools=[])


def test_http_observe_guard_wire_shape_omits_unset_fields(monkeypatch):
    c = _client()
    captured = {}

    def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return 200, {"observation": {"agent_id": "a", "project": "p", "tools": body["tools"]}}

    monkeypatch.setattr(c, "_post", fake_post)

    tools = [
        GuardToolObservation(
            name="contact_customer",
            parameter_schema={"type": "object", "properties": {"customer_id": {}, "channel": {}}},
            entity_arg="customer_id", action="CONTACT_CUSTOMER", entity_type="Customer",
            observed_call_count=2,
        ),
        GuardToolObservation(name="bare_tool"),  # only a name; everything else unset
    ]
    c.observe_guard(agent_id="a", adapter="agno", mode="enforce", tools=tools,
                    project="cookbook", sdk_version="0.1.0")

    assert captured["path"] == "/v1/guard/observations"
    body = captured["body"]
    assert body["agent_id"] == "a" and body["adapter"] == "agno" and body["mode"] == "enforce"
    assert body["project"] == "cookbook" and body["sdk_version"] == "0.1.0"
    # environment / workflow were unset -> omitted.
    assert "environment" not in body and "workflow" not in body

    t0 = body["tools"][0]
    assert t0 == {
        "name": "contact_customer",
        "parameter_schema": {"type": "object", "properties": {"customer_id": {}, "channel": {}}},
        "entity_arg": "customer_id",
        "action": "CONTACT_CUSTOMER",
        "entity_type": "Customer",
        "observed_call_count": 2,
    }
    # bare tool carries ONLY its name — no None fields leak onto the wire.
    assert body["tools"][1] == {"name": "bare_tool"}


def test_http_observe_guard_parses_observation_response(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_post", lambda path, body: (200, {"observation": {
        "tenant_id": "t", "project": "cookbook", "environment": "aws",
        "agent_id": "customer-ops-team", "workflow": "vulnerability-escalation",
        "tools": [{"name": "contact_customer", "action": "CONTACT_CUSTOMER",
                   "entity_type": "Customer", "entity_arg": "customer_id",
                   "observed_call_count": 2}],
        "observed_at": "2026-06-12T00:00:00Z", "updated_at": "2026-06-12T00:00:01Z",
    }}))
    obs = c.observe_guard(agent_id="customer-ops-team", adapter="agno", mode="enforce", tools=[])
    assert obs.tenant_id == "t" and obs.project == "cookbook"
    assert obs.tools[0].action == "CONTACT_CUSTOMER"
    assert obs.tools[0].observed_call_count == 2


def test_http_observe_guard_transport_error_raises(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_post", lambda path, body: (0, {"message": "transport error: down"}))
    with pytest.raises(ConnectionError, match="guard observe failed"):
        c.observe_guard(agent_id="a", adapter="agno", mode="enforce", tools=[])


def test_http_observe_guard_non_2xx_raises(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_post", lambda path, body: (401, {"error": "unauthorized"}))
    with pytest.raises(ConnectionError, match="unauthorized"):
        c.observe_guard(agent_id="a", adapter="agno", mode="enforce", tools=[])
