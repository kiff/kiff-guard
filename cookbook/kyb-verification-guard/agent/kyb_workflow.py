"""kyb_workflow — an Agno *Workflow* with KIFF guard via agno_hook.

This recipe shows the structured shape: a KYB onboarding pipeline built as
an Agno `Workflow` of ordered steps:

    intake (function)  ->  verify (Agent + run_kyb_check tool)  ->  decision (function)

The `verify` step's tool, `run_kyb_check`, is a PAID bureau verification
(Companies House + sanctions + UBO screen). KIFF gates it so it runs
EXACTLY ONCE: allowed while the business is PENDING, blocked once VERIFIED.
A retried or re-entered workflow — a flaky run, a duplicate trigger, an
operator re-submitting — cannot pay the bureau twice or re-screen a decided
entity.

Guardrails PLUS KIFF (not instead of):

  Agno guardrails are *pre_hooks* validating the workflow/agent INPUT
  (PII, prompt injection). KIFF is a *tool_hook* deciding whether the
  verification ACTION may run given the onboarding state. The guardrail
  keeps the input clean; KIFF keeps the bureau call once-and-done.

Environment:
  OPENAI_API_KEY, KIFF_BASE_URL, KIFF_CLOUD_API_KEY, KIFF_CLOUD_URL, KYB_APP_URL
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "packages", "python", "kiff-guard", "src"))

from kiff_guard import Guard, HTTPClient, ToolMap
from kiff_guard.adapters.agno import agno_hook

KIFF_BASE_URL = os.environ.get("KIFF_BASE_URL", "http://localhost:8081")
KIFF_CLOUD_API_KEY = os.environ.get("KIFF_CLOUD_API_KEY", "")
KIFF_CLOUD_URL = os.environ.get("KIFF_CLOUD_URL", "https://api.kiff.dev")
KYB_APP_URL = os.environ.get("KYB_APP_URL", "http://localhost:8082")


def _post(url, body):
    from urllib import request as urllib_request
    data = json.dumps(body).encode()
    req = urllib_request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib_request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def build_guard() -> Guard:
    tool_map = ToolMap().bind(
        "run_kyb_check",
        action="RUN_KYB_CHECK",
        entity_type="Business",
        entity_arg="business_id",
    )
    client = HTTPClient(api_key="local", tool_map=tool_map, base_url=KIFF_BASE_URL)
    guard = Guard(client=client, tenant="cookbook", agent="kyb-workflow", mode="enforce")

    if KIFF_CLOUD_API_KEY:
        try:
            cloud_client = HTTPClient(
                api_key=KIFF_CLOUD_API_KEY, tool_map=tool_map, base_url=KIFF_CLOUD_URL,
            )
            conn = cloud_client.connect_guard(
                agent_id="kyb-workflow", adapter="agno", mode="enforce",
                project="cookbook", environment="aws", workflow="kyb-verification",
                sdk_version="0.1.0",
            )
            print(f"  Connected to KIFF Cloud: runtime={conn.runtime_id}")
        except Exception as e:
            print(f"  Cloud connect skipped: {e}")

    return guard


def _maybe_pii_guardrail():
    """Return [PIIDetectionGuardrail()] if this Agno build ships it, else []."""
    try:
        from agno.guardrails import PIIDetectionGuardrail
        return [PIIDetectionGuardrail()]
    except Exception:
        return []


def create_verification_agent(guard: Guard):
    """The agent that runs inside the workflow's `verify` step."""
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.tools import tool

    @tool
    def run_kyb_check(business_id: str, registration_number: str) -> str:
        """Run a paid bureau KYB verification (Companies House + sanctions + UBO)."""
        result = _post(f"{KYB_APP_URL}/verify",
                       {"business_id": business_id, "registration_number": registration_number})
        # A successful, cleared verification advances the onboarding state.
        _post(f"{KIFF_BASE_URL}/v1/events/raw",
              {"business_id": business_id, "type": "KYB_VERIFIED", "actor_id": "kyb-workflow"})
        return json.dumps(result)

    return Agent(
        name="KYB Verification Agent",
        role="Run the bureau KYB verification exactly once for a pending business.",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[run_kyb_check],
        tool_hooks=[agno_hook(guard)],
        pre_hooks=_maybe_pii_guardrail(),
        instructions=["Call run_kyb_check with the business_id and registration_number."],
    )


def create_kyb_workflow(guard: Guard):
    """Build the Agno Workflow: intake -> verify (guarded) -> decision.

    Returns (workflow_or_None, verify_agent). If this Agno build doesn't
    expose Workflow/Step, workflow is None and the driver runs the verify
    agent directly — the KIFF guarantee is identical either way.
    """
    verify_agent = create_verification_agent(guard)

    try:
        from agno.workflow import Step, Workflow, StepOutput

        def intake(step_input):
            return StepOutput(content=f"Intake complete for: {step_input.input}")

        def decision(step_input):
            return StepOutput(content=f"KYB decision recorded. Prior step: {step_input.input}")

        workflow = Workflow(
            name="KYB Onboarding",
            steps=[
                intake,                       # function step
                Step(name="verify", agent=verify_agent),  # guarded agent step
                decision,                     # function step
            ],
        )
        return workflow, verify_agent
    except Exception:
        return None, verify_agent


def run_workflow(workflow, verify_agent, message: str) -> str:
    if workflow is not None:
        response = workflow.run(message)
    else:
        response = verify_agent.run(message)
    if hasattr(response, "content"):
        return response.content
    return str(response)
