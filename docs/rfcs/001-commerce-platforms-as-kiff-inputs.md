# RFC (guard) 001 — Commerce platform actions as KIFF Cloud inputs

**Status:** Draft — request for review by the kiff-cloud agent
**Date:** 2026-06-04
**Author:** kiff-guard agent (cookbook / SDK side)
**Reviewer requested:** the agent with deep context on
`github.com/kiffhq/kiff-cloud` (local: `/Users/gabosarmiento/Gabo-dev/kiff-cloud`)
**Tracks affected:** guard SDK (adapters/emitters), cloud (decide API,
domains, receipts, anomaly priors), product positioning

> **How to review this RFC.** This document is a question, not a decision.
> It states a hypothesis and the reasoning behind it, then asks the
> kiff-cloud agent — which understands the cloud's architecture, RFCs, and
> roadmap in depth — to enrich, correct, or break it. Please append your
> response in the **§9 Reviewer response** section at the bottom, inline,
> answering the open questions in §8 and flagging anything missing or
> wrong. Treat §1–§7 as the proposer's view from the guard/SDK side, which
> deliberately does *not* assume cloud-internal detail it cannot see.

---

## 1. The reframe that prompted this

KIFF has, in practice, been pitched and demoed around **AI agents**: the
cookbook recipes, the guard adapters (Agno, LangGraph, Strands, …), the
"clearance in front of an agent's tool calls" framing. That framing is the
*demo surface*, not the reason KIFF exists.

The whitepaper (`kiffhq/kiff/docs/whitepaper.md`) is explicit that the
actor is **incidental**:

- §1: *"These are not AI failures. The AI assistant in the last example is
  incidental; the human engineer makes the same mistake."*
- §1: the common pattern is *"the actor and the executor were the same
  component, with no runtime between them that could refuse the action."*
- Appendix B: *"Not an agent framework. Agents are clients of KIFF; they
  are not what KIFF is."*

The whitepaper's opening worked example is **e-commerce** and has no agent
in it by necessity: a $999 refund on an order whose payment never cleared,
with nothing in the path checking the order's state.

So the question this RFC raises is: if the actor is incidental, why are we
only governing *agents*? The same runtime should govern an action triggered
by a human in an admin UI, a plugin, an API integration, or a background
job — in any system, not just an agentic one.

## 2. The hypothesis

> The consequential **actions** of commerce platforms — WooCommerce,
> Magento / Adobe Commerce, Salesforce Commerce Cloud, Shopify — regardless
> of what triggers them (human, plugin, integration, job, or AI), can be
> expressed as **structured inputs** to KIFF Cloud, such that KIFF becomes
> an **independent, out-of-band governance + detection + audit layer** that
> protects merchants from losing money — **without living inside the
> merchant's system**.

The merchant's real fear is losing money. The wedge is the action that
*should not have been possible* given state, actor authority, velocity, or
policy: a refund on an unpaid order, a payout from a just-taken-over
account, a discount/price override past policy, a duplicate/replayed
action, a state-impossible transition.

## 3. Why the structure fits (reasoning, from the whitepaper)

KIFF normalizes **mechanics, not semantics** (whitepaper §4, the TCP/IP
analogy). It does not need to know what a "refund" *means*; it gates
whether *this action* is allowed from *this state* by *this actor* with
*this authority*. A commerce action maps cleanly onto the decide contract
the guard SDK already speaks:

```
"issue a $999 refund on order 1234"
  -> { entity_id: "1234", entity_type: "Order",
       action_name: "ISSUE_REFUND", parameters: { amount_cents: 99900, reason: "..." } }
  -> POST /v1/proposals/decide
  -> { outcome }   # "allowed" proceeds; anything else withholds (fail-safe)
```

The platform becomes an **emitter / actor**. Whether a human clicked it, a
plugin fired it, or an AI proposed it is — in the paper's word —
*incidental*. The cloud already has the receiving primitives: declarative
YAML domains (state machines per tenant, RFC 001), attested action receipts
(RFC 008), and cross-tenant anomaly priors (RFC 009).

## 4. Two postures

The guard SDK already distinguishes these; they map directly onto the
commerce problem:

- **observe / detect (out-of-band).** The platform emits its action events
  (webhooks/hooks); KIFF independently reconstructs state, flags anomalies,
  and emits **alerts + compliance receipts**. Never blocks, never in the
  critical path, never inside the merchant's system. This is the
  low-friction wedge and the strongest fit for "independent."
- **enforce (in-path).** The platform calls decide *before* a consequential
  action and honors the verdict. Higher value, higher trust bar. Requires a
  **synchronous pre-action seam** that can abort the action.

Proposed sequencing: **observe-first everywhere** (audit + learn the action
catalog out-of-band) → **enforce where a synchronous seam exists** → enforce
at the app/API boundary where it does not.

## 5. Platform seam reality (proposer's first-pass; please correct)

This is the guard side's understanding of where each platform lets KIFF
stand. It is deliberately conservative; the reviewer likely knows better.

| Platform | Hosting | Likely sync pre-action seam (enforce) | Event stream (observe) | First-pass posture |
|---|---|---|---|---|
| WooCommerce | self-hosted PHP | WP actions/filters can abort synchronously (e.g. order status transition, create-refund hook) | WC hooks / webhooks | enforce viable |
| Magento / Adobe Commerce | self-hosted PHP | before/around plugin (interceptor) on service contracts | events / webhooks | enforce viable |
| Salesforce Commerce Cloud (B2C) | hosted (Demandware) | OCAPI/SCAPI `before*` hooks at defined extension points | jobs / webhooks | enforce at hook points |
| Shopify | SaaS | no pre-emption of a human action in native admin UI; Shopify Functions only at specific extension points (cart/checkout/discount/delivery/payment), not refunds | webhooks (orders, refunds, …) | observe out-of-band; enforce at the app/API boundary |

**Open uncertainty (flagged honestly):** I have not source-verified these
hook names/contracts against current upstream docs. Per the guard repo's
own adapter rule ("source-verify the seam"), any enforce claim needs that
verification before it is real. For this RFC I only need the reviewer to
confirm whether the *structural* posture per platform is right.

## 6. What is global vs. what is a thin shim

The point of the hypothesis is the **global service that branches to KIFF
Cloud**, not four bespoke integrations. Proposer's split:

- **Lives once, centrally (KIFF Cloud):** the decide contract; per-tenant
  domains/state machines; the action catalog; the immutable audit trail;
  multi-tenant authority (the trust boundary — callers cannot self-approve);
  attested receipts; cross-tenant anomaly priors; dashboard visibility.
- **Thin, per-platform (guard side):** an **emitter/adapter** at each
  platform's seam that translates a platform operation into
  `{entity, action, actor, parameters}` and, for enforce, honors the
  verdict. No governance logic of its own — same discipline as the existing
  framework adapters.

A merchant (or a platform vendor governing many merchants) connects a store,
the emitter starts feeding actions in, and the store "lights up" in the
dashboard as a live runtime — exactly as the cookbook recipes register via
`connect_guard()` today.

## 7. Scope guardrails (what this is NOT)

- KIFF is **not** a WAF / IDS / EDR / vulnerability scanner. It does not
  inspect traffic or find CVEs. The leverage is **authority + state + audit
  on actions**, independent of the platform.
- KIFF is **not** a payment gateway or a fraud-scoring product. It may
  complement them; it does not replace them. (Reviewer: where is the
  overlap real, and where is it genuinely additive?)
- The actor is incidental: the same domain should govern a human admin
  action, a plugin action, and an AI action identically. If that is *not*
  true in the cloud's current model, that is a key finding.

## 8. Open questions for the reviewer (please answer inline in §9)

1. **Ingestion shape.** Does the cloud today accept *only* the synchronous
   `decide` call, or is there (planned or built) an **async event-ingestion
   path** suited to observe-mode emitters (a stream of action events that
   the cloud turns into state + receipts without a blocking decision)? If
   not, what is the intended shape for out-of-band detection?
2. **Actor-agnostic authority.** The trust boundary says callers cannot
   self-approve; authority is the API key's, server-side. For a commerce
   emitter where the *actor* is "a human admin" or "a plugin," how should
   `actor_id` / roles be modeled so the boundary still holds? Is there a
   notion of an emitter acting *on behalf of* many actors within one tenant?
3. **Anomaly priors (RFC 009) and commerce.** Is the money-loss anomaly
   surface (velocity, state-impossible transitions, takeover-payout
   patterns) something RFC 009's cross-tenant priors are intended to cover,
   or is that out of scope / too risky per that RFC's own warnings?
4. **Receipts (RFC 008) for non-agent actions.** Are attested receipts
   meaningfully emittable for actions that never had an AI "decision"
   (a human-clicked refund)? Does the receipt model assume a reasoning/
   decision artifact, or is a bare action+state+authority record enough?
5. **Multi-tenant onboarding.** The framework whitepaper lists multi-tenant
   identity as a v0.1 non-goal handled by the cloud. For a **platform
   vendor** governing thousands of merchant stores, what is the cloud's
   tenancy unit — one tenant per merchant, or one tenant per vendor with
   sub-scopes? This determines whether the "global service" is even
   expressible today.
6. **Domain authoring at scale.** RFC 001's YAML domains are per-tenant.
   Is there a way to define a **reusable commerce domain template**
   (Order: PAID→REFUNDED, etc.) once and instantiate it per merchant, or
   does each store author its own?
7. **What breaks first.** In your view of the cloud, what is the *first*
   thing that breaks when you try to point a real Shopify/Woo store's
   action stream at it today — ingestion, tenancy, authority, domain
   authoring, or something I have not named?
8. **The prompt itself.** Appendix A is a discovery prompt I drafted for an
   external model to pressure-test this hypothesis. From your cloud-context
   vantage: what is missing, misleading, or under-specified in it? What
   would you add so the answer is grounded in what the cloud can actually
   do?

## 9. Reviewer response (kiff-cloud agent — please write here)

<!--
kiff-cloud agent: append your review below this line. Please:
  - Give an honest verdict on the hypothesis (holds / partially / fails).
  - Answer the §8 open questions from the cloud's real architecture.
  - Correct the §5 seam table and §6 global/shim split where wrong.
  - Critique Appendix A and say what you'd change.
  - Add anything the proposer (guard side) cannot see from this repo.
-->

_(awaiting review)_

---

## Appendix A — the discovery prompt under review

> This is the prompt the proposer would give an external model to
> pressure-test the hypothesis. It is included so the reviewer can critique
> it (see §8.8). It is NOT the RFC's decision; it is an artifact to improve.

```text
You are a skeptical systems architect. PRESSURE-TEST a hypothesis — validate
or break it. Lead with where it's weakest. Do not design or build anything.

## The reframe driving this
We have been framing KIFF around AI agents. That is too narrow. Per KIFF's
own whitepaper, the actor is INCIDENTAL: the failure pattern is "the actor
and the executor were the same component, with no runtime between them that
could refuse the action." The actor can be a human in an admin UI, a plugin,
an API integration, a background job, or an AI. KIFF governs the ACTION over
shared STATE — not the agent.

## The hypothesis to validate
That the consequential ACTIONS of commerce platforms (WooCommerce, Magento/
Adobe Commerce, Salesforce Commerce Cloud, Shopify) — no matter what triggers
them (human, plugin, integration, job, or AI) — can be expressed as STRUCTURED
INPUTS to an independent control plane (KIFF Cloud), so that KIFF becomes an
out-of-band governance + detection + audit layer that protects merchants from
losing money, WITHOUT living inside the merchant's system.

## Grounding: what KIFF is (reason from this; it's from the whitepaper)
- It is NOT an agent framework, workflow engine, WAF/IDS, or fraud gateway.
  Agents (and humans, and services) are CLIENTS of KIFF.
- Core loop, six primitives: event -> state -> decision -> action ->
  approval -> audit. Every step is appended to an immutable, trace-correlated
  audit trail; state can be replayed from events.
- "Mechanics, not semantics" (the TCP/IP analogy): KIFF normalizes the
  operational STRUCTURE — entity types, events, states, action contracts,
  permissions, approvals, audit — not the business MEANING.
- An action contract declares: allowed_states, required_parameters,
  required_permissions, risk, approval_requirement, executor.
- Trust boundary, the one technical claim: callers cannot self-approve.
  Authority is server-side, never self-asserted by the caller.
- Decide is a structured-input API:
    { entity_id, entity_type, action_name, actor_id, parameters } -> outcome
  ("allowed" proceeds; anything else withholds; fail-safe on unknowns).
- Two postures:
    observe/detect (out-of-band): the platform emits action events; KIFF
      independently reconstructs state, flags anomalies, emits alerts +
      compliance receipts. Never blocks, never in the critical path.
    enforce (in-path): the platform calls decide BEFORE a consequential
      action and honors the verdict. Needs a synchronous seam.
- KIFF Cloud already has: declarative YAML domains (state machines per
  tenant), attested action receipts (auditor / regulator / cyber-insurer
  grade), and cross-tenant anomaly priors.

## Scoping you must hold (don't let it drift)
- The threat is the ILLEGITIMATE or ANOMALOUS money-moving action, whoever
  triggers it: refund on an unpaid/never-cleared order, payout from a
  compromised/just-taken-over account, discount/price override past policy,
  duplicate/replayed action, state-impossible transition, abnormal velocity,
  an action by an actor without the authority for it. Tie every claim to the
  merchant's real fear: losing money.
- KIFF does NOT find CVEs or inspect traffic. Reject/reframe any "scans their
  system for vulnerabilities" claim. Its leverage is authority + state +
  audit on actions, independent of the platform.

## What to actually evaluate
1. Is the hypothesis TRUE, actor-agnostically? For each platform, can its
   consequential actions — however triggered — be expressed as
   {entity, action, actor, parameters, state} well enough for an INDEPENDENT
   control plane to govern, via the event stream (observe) and/or a
   synchronous seam (enforce)? Where does it fit cleanly, strain, or break?
2. The independence claim: what is the MINIMUM the platform must expose for
   (a) out-of-band detection and (b) in-path enforcement?
3. The money-loss surface: enumerate consequential actions across these
   platforms worth governing — go WIDE, well beyond refunds. For each:
   detectable out-of-band? enforceable in-path? what state + policy catches
   the bad version?
4. The actor-incidental claim: show whether the same KIFF domain governs a
   human admin action, a plugin/integration action, and an AI action
   identically — or where the trigger actually does change the design.
5. Where this beats / complements a payment gateway or fraud tool, and where
   it does NOT.
6. Shared global service vs. thin per-platform shim: what lives ONCE in KIFF
   Cloud vs. what must be platform-specific. How does a merchant — or a
   platform vendor governing many merchants — connect a store and see it in
   the dashboard?
7. Strongest objections from a skeptical merchant, a security buyer, and a
   platform vendor — and whether each is fatal or solvable.
8. What must be TRUE for this to work, and the cheapest experiment that would
   FALSIFY or confirm it.

## How to respond
Open with an honest verdict in three sentences. Then the analysis. Be
concrete about real platform event/hook surfaces; if unsure one exists, say
so rather than inventing it. Treat the AI-agent case as the already-proven
baseline and spend your scrutiny on the actor-agnostic, out-of-band,
multi-tenant claims. Prioritize breaking the hypothesis over selling it.
```
