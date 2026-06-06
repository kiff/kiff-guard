"""Guard.save_draft + HTTPClient.save_draft — the credentialed half of
instrument-first authoring (PUT /v1/me/domain/draft).

Tests run with no cloud: the Guard path uses a stub DraftSaver, and the
HTTPClient path monkeypatches the transport (_put_yaml) to script cloud
responses, so response parsing and error handling are covered offline.
"""

from __future__ import annotations

import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kiff_guard import DraftResult, Guard, HTTPClient, ToolMap  # noqa: E402


class _StubSaver:
    """A client that implements only save_draft (the DraftSaver shape)."""

    def __init__(self, result=None):
        self.saved_yaml = None
        self._result = result or DraftResult(yaml="", updated_at=7, valid=True)

    def save_draft(self, yaml_text):
        self.saved_yaml = yaml_text
        return self._result


class _BareClient:
    def decide(self, *a, **k):
        ...


# --- Guard.save_draft ------------------------------------------------------

def test_save_draft_requires_a_client():
    guard = Guard(mode="observe", agent="a")  # no client
    with pytest.raises(ValueError, match="requires a client"):
        guard.save_draft("acme")


def test_save_draft_requires_client_with_save_draft():
    guard = Guard(client=_BareClient(), tenant="t", agent="a", mode="observe")
    with pytest.raises(ValueError, match="save_draft"):
        guard.save_draft("acme")


def test_save_draft_renders_catalog_and_forwards_yaml():
    saver = _StubSaver()
    guard = Guard(client=saver, tenant="t", agent="support", mode="observe")
    guard.observe("refund_order", {"order_id": "o1", "amount_cents": 5})

    result = guard.save_draft("order-refunds")

    # The YAML the guard sent is the schema-shaped derived draft.
    doc = yaml.safe_load(saver.saved_yaml)
    assert doc["domain"] == "order-refunds"
    action = next(a for a in doc["actions"] if a["name"] == "refund_order")
    assert set(action["required_parameters"]) == {"order_id", "amount_cents"}
    assert result.valid is True and result.updated_at == 7


def test_save_draft_returns_cloud_result_with_issues():
    saver = _StubSaver(result=DraftResult(yaml="x", updated_at=3, valid=False, issues=["bad state ref"]))
    guard = Guard(client=saver, tenant="t", agent="a", mode="observe")
    guard.observe("send_email", {"to": "x"})
    result = guard.save_draft("d")
    assert result.valid is False
    assert result.issues == ["bad state ref"]


# --- HTTPClient.save_draft response parsing + errors -----------------------

def _client():
    return HTTPClient(api_key="kiff_live_t_x", tool_map=ToolMap(), base_url="https://api.example")


def test_http_save_draft_empty_yaml_raises():
    with pytest.raises(ValueError, match="non-empty"):
        _client().save_draft("   ")


def test_http_save_draft_parses_valid_response(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_put_yaml", lambda path, body: (200, {
        "yaml": "domain: d\n", "updated_at": 42, "parsed": {"domain": "d"},
    }))
    res = c.save_draft("domain: d\n")
    assert res.valid is True and res.updated_at == 42 and res.issues == []


def test_http_save_draft_parses_issues_response(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_put_yaml", lambda path, body: (200, {
        "yaml": "domain: d\n", "updated_at": 9,
        "issues": [{"message": "unknown executor"}, {"message": "no states"}],
    }))
    res = c.save_draft("domain: d\n")
    assert res.valid is False
    assert res.issues == ["unknown executor", "no states"]


def test_http_save_draft_transport_error_raises(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_put_yaml", lambda path, body: (0, {"message": "transport error: down"}))
    with pytest.raises(ConnectionError, match="save draft failed"):
        c.save_draft("domain: d\n")


def test_http_save_draft_non_2xx_raises(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_put_yaml", lambda path, body: (401, {"error": "unauthorized"}))
    with pytest.raises(ConnectionError, match="unauthorized"):
        c.save_draft("domain: d\n")


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            # crude monkeypatch shim for __main__ runs
            fn() if "monkeypatch" not in fn.__code__.co_varnames else None
            passed += 1
        except Exception:
            traceback.print_exc()
    print(f"{passed} ran (use pytest for monkeypatch tests)")
