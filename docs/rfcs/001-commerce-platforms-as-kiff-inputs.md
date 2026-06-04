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

> **Reviewer:** kiff-cloud agent (deep context on `github.com/kiffhq/kiff-cloud`
> and its `docs/design` RFCs). Reviewed 2026-06-04 against the cloud's real
> architecture (RFCs 001–018) and the live API/handlers, not from memory.

### Verdict

**Partially holds — and the part that holds is the weaker half of the pitch.**
The *structural* claim is true and already proven by the cloud's own design:
KIFF normalizes mechanics not semantics, the decide contract is actor-agnostic
by construction (`actor_id` is just a field; authority is the key's, server-side),
and a commerce action maps onto `{entity, action, actor, parameters, state}`
cleanly. So "commerce actions as structured inputs" is real. **But three load-
bearing assumptions in the RFC are not backed by what the cloud can do today:**
(1) the *out-of-band observe posture* does **not** produce the cloud's flagship
artifact — the attested receipt's value proposition is "before the money moved,
something independent authorized it," which is only true in **enforce** mode;
observe gives you detection + audit + a *retrospective* record, not Exhibit A;
(2) the *money-loss anomaly surface* (velocity, takeover-payout, abnormal rate)
is **not built and not covered by RFC 009** — that RFC is opt-in, off-by-default,
statistical incident-rate *priors*, possibly-to-be-killed, and explicitly **not**
a real-time anomaly detector; (3) the *"platform vendor governing thousands of
stores"* framing is **not expressible in the current tenancy model** (RFC 003 is
flat: one tenant = one schema = one domain = one key/role-set; there is no
vendor→sub-store hierarchy). The hypothesis is a good north star and the
enforce-mode, single-merchant version is shippable on today's primitives. The
out-of-band + multi-tenant-vendor + real-time-detection version is roadmap, and
some of it (velocity detection) isn't on any roadmap yet. Treat §1–§4 as
directionally correct and §5–§8's implicit "the cloud already has the receiving
primitives" as **half-true**: it has decide, domains, schema-isolation, and
execution receipts; it does **not** have observe-mode receipts, anomaly
detection, or vendor-scoped tenancy.

---

### Answers to §8 (from the cloud's real architecture)

**Q1 — Ingestion shape.** Both paths exist, but they do different things and
this distinction is the crux the RFC glosses:

- `POST /v1/proposals/decide` (RFC 017, contract frozen) — **synchronous,
  blocking verdict.** Records a proposal + decision, returns one of
  `allowed | approval_required | blocked | invalid | limit_exceeded`. This is
  the enforce seam.
- `POST /v1/events/raw` — **async-ish ingestion.** Ingests an event, advances
  entity state deterministically, writes the audit trail. **No proposal, no
  decision verdict, no receipt.** This is what the guard SDK's `observe()` and
  `export_yaml()` lean on (RFC 014 instrument-first: observe blocks nothing,
  audits everything, and *derives* the action catalog from real traffic).

So the honest shape for an out-of-band emitter today is: stream actions to
`events/raw` to build state + an audit trail, and — if you want a *verdict* on
each action — *also* call `decide` after the fact. But a post-hoc `decide` is a
**shadow decision**: the action already executed in the merchant's system, so
the outcome is detection, not prevention. There is **no built path that turns a
stream of already-happened actions into attested receipts** without modeling
each as a decide+execute through the cloud's runtime. If observe-mode receipts
are part of the wedge, that's net-new cloud work, not a config of what exists.

**Q2 — Actor-agnostic authority & the self-approval boundary.** The boundary
holds, and the RFC's instinct is right: authority is the authenticated key's,
resolved server-side; `roles` is **deliberately rejected from the request body**
(RFC 017; guard conformance invariant E3) precisely so a caller cannot self-
assert authority. `actor_id` is advisory provenance, *not* authority — it labels
"who triggered this" for the audit trail; it does not grant anything. So for a
commerce emitter:

- Model the **emitter** as the tenant's API key, carrying the role(s) the
  domain grants (exactly like the demo tenant's key carries `admin`/`shift_manager`).
- Pass the real-world trigger ("human admin jane@", "plugin X", "cron") as
  `actor_id` for provenance.
- **The gap the RFC should name:** there is no first-class "emitter acting on
  behalf of many distinct actors with *different* authority within one tenant."
  Every call from one key carries that key's roles. If you need "admin Jane may
  refund but support-agent Bob may not," that's *not* expressible by one emitter
  key — you'd need per-actor keys (one tenant, many keys, each role-scoped) or a
  domain that encodes the distinction in `required_permissions` plus a key per
  authority tier. The runtime authorizes the *key's* roles against the active
  domain, full stop. Per-actor authority within a single emitter is unsolved.

**Q3 — Anomaly priors (RFC 009) vs the money-loss surface.** This is the
biggest overclaim in the RFC. RFC 009 does **not** cover the surface you want,
and it may never ship:

- RFC 009 is **Draft, high-risk, with explicit kill criteria** (privacy/
  re-identification, perceived betrayal, regulatory exposure). It ships **zero
  engineering** until a trust-appetite experiment (#41) returns "proceed" and
  external counsel signs off. Do not design a commerce product assuming it
  exists.
- Even if it ships, it is **opt-in, off by default, per-domain**, and returns
  `null` below `n>=30` per action shape — so for the first 12–18 months it is
  `null` for almost everything.
- What it actually is: a **statistical prior** — a 5-field tuple
  (`action_shape_hash`, `entity_state_at_decision`, `approval_outcome`,
  `incident_within_30d`, `dataset_version`) that populates the `risk_score` on
  a receipt with a *historical incident rate for action shapes of this type*.
  It is **not** a real-time detector. It has **no notion of velocity, of
  takeover, of per-account rate, of sub-day timing** (timestamps finer than a
  day are deliberately excluded for privacy).

Where the money-loss surface is *actually* covered today: **state-impossible
transitions** are caught by the domain state machine for free (a refund on an
order not in `PAID` returns `state_not_allowed` / `invalid` — this is the
$999-refund whitepaper case and it genuinely works). **Duplicate/replayed
actions** are partially covered by the idempotency key (`id`) on decide.
**Velocity, takeover-payout patterns, abnormal rate** are covered by **nothing**
— not the runtime, not RFC 009. Those would be a new detection capability the
cloud does not have and has not scoped. The RFC should split its "detection"
claim into "state/authority/duplicate violations (real today, via the domain +
decide)" and "behavioral anomalies (not built, and RFC 009 is the wrong tool
for it)."

**Q4 — Receipts (RFC 008) for non-agent actions.** Good news and a caveat.
The receipt does **not** assume an AI reasoning artifact — `reasoning_summary`
and `confidence` are *optional, advisory* fields on decide (RFC 017 classes
them as "advisory/may-change"). The receipt's six fields are `causal_chain`,
`attestation`, `risk_score` (nullable), `replay_link`, `compliance_map`,
`insurer_envelope`. A bare **action + state + authority + decision** record is
enough to populate the causal chain; a human-clicked refund attests perfectly
well. So **yes, receipts are meaningful for non-agent actions** — this part of
the hypothesis holds cleanly.

The caveats: (a) receipts are emitted at **action-execution time** through the
cloud's runtime (default: approval-required actions; opt-in for the rest), so
they presuppose the **enforce/decide+execute** path, not observe — see Q1; in
observe mode you have audit records but not the RFC 008 receipt artifact unless
new work models observed actions as executions. (b) The receipt's *marketed*
value is "before the money moved, something independent authorized it" (RFC 008
+ landing copy). That sentence is **only true in enforce mode.** An observe-mode
receipt would have to be worded as "independently recorded and verified after
the fact," which is a real but materially weaker compliance claim. (c)
`attestation` (the Base anchor) is real but **Base Sepolia testnet only** today
(`apps/api/contract/deployments.json` — contract `0x2F54…DEa4`, deployer
`0x2f29…fCbE`); production-mainnet anchoring is RFC 007 "production form," not
shipped. Don't promise auditor/insurer-grade anchoring to a merchant on a
testnet artifact.

**Q5 — Multi-tenant onboarding for a platform vendor.** This is the structural
blocker for the "global service governing thousands of stores" framing. RFC 003
is **schema-per-tenant**: each tenant = one Postgres schema `kiff_t_<id>`, one
active domain, one key/role-set, resolved by `search_path` per request. There is
**no org/vendor tier, no sub-tenant scoping, no hierarchy.** So today the
tenancy unit can only be **one tenant per merchant store**. A platform vendor
governing 3,000 stores = 3,000 tenants = 3,000 schemas = 3,000 domains = 3,000
keys, with **no built-in concept of "the vendor" above them** — no cross-store
dashboard, no fleet management, no vendor-scoped billing roll-up. RFC 003's own
open questions flag that the shared connection pool has no per-tenant limits
("noisy tenant exhausts the pool; acceptable for the first 50 tenants") — 3,000
schemas is far outside the v0.1 envelope. **The "global service" is not
expressible today.** The minimum new work: a vendor/org entity above tenants,
fleet provisioning, and a tenancy-scale review of schema-per-tenant at thousands
(it may force a move toward the row-level model RFC 003 explicitly rejected, or
a hybrid). This belongs in a new cloud RFC before any vendor-facing commitment.

**Q6 — Domain authoring at scale / reusable templates.** Partially there. The
mechanism exists: starter-domain **templates** are applied via
`POST /v1/me/domain/template` (today's catalog: `cafe-ops`, `refund-agno`), and
Studio authors per-tenant YAML (RFC 001 + RFC 012). So "define a commerce domain
once, instantiate per merchant" is *possible* at the per-tenant level — apply
the same template slug to each new tenant. **But** there is no "define once,
propagate to a fleet, version centrally, push an update to 3,000 stores at once"
provisioning system. Each tenant gets its own copy at apply time; a later
template change does not retro-update tenants that already applied it (the
demo-key rotation work this week confirmed apply is per-tenant and version-
bumping). RFC 016 (KIFF Templates surface — pre-filled blueprints + a Match
helper) is the closest planned thing and is post-launch/unbuilt. So: per-merchant
instantiation from a shared template = yes; centrally-managed fleet domains =
not yet.

**Q7 — What breaks first when you point a real store's action stream at the
cloud today.** Ranked, most-immediate first:

1. **Volume + metering/quota economics.** The free plan caps at ~1,000 governed
   proposals/period (RFC 004 counters; `limit_exceeded` is a real outcome). A
   live store's full action stream (every order/refund/inventory/discount event)
   blows that in hours, and each `decide` is a billable unit. The pricing model
   (RFC 008: per-receipt; RFC 018: per protected control) is built for a *small
   number of high-value money-moving controls*, **not** a firehose of every
   platform action. Pointing the whole stream at the cloud is an economic
   non-starter before it's a technical one — you must filter to the consequential
   action set at the emitter.
2. **Observe-mode receipt gap (Q1/Q4).** `events/raw` gives audit, not receipts/
   verdicts; the artifact the product sells doesn't materialize from a raw stream.
3. **Tenancy unit for a multi-store vendor (Q5).** Fine for one store; breaks the
   moment "one vendor, many stores" is the shape.
4. **Per-actor authority within one emitter (Q2).** One key = one role-set; real
   stores have many actors with different authority.
5. **Connection-pool/schema scale (RFC 003).** Beyond ~50 active tenants the
   shared-pool assumption needs revisiting.

Note what does **not** break: the decide contract itself, the state-machine
gating of impossible transitions, and execution receipts for a *curated* set of
high-value actions on a *single* tenant. That's exactly the RFC 018 "Control
Proof" wedge — one merchant, a few protected money-moving controls, enforce mode.
Start there; the firehose/observe/fleet story is a different, larger build.

**Q8 — Critique of the Appendix A discovery prompt.** It's a strong prompt;
it's honest about scope and rejects the WAF/scanner drift well. Gaps that would
make an external model's answer *more grounded in what the cloud can actually
do*:

- **It asserts capabilities as present that are not.** "KIFF Cloud already has:
  declarative YAML domains, attested action receipts, and cross-tenant anomaly
  priors." Domains: yes. Receipts: **execution-time only, Base Sepolia testnet,
  RFC 008 still Draft.** Anomaly priors: **Draft, off-by-default, may be killed,
  not a detector.** Feed the model the *status* of each (built / draft / unbuilt)
  or it will reason from a cloud that doesn't exist.
- **It conflates "observe = detection" with the receipt.** Add the explicit
  constraint: *observe ingests events and reconstructs state/audit but does not,
  today, emit a pre-execution verdict or an attested receipt; the "before the
  money moved" claim is enforce-only.* This is the single most important framing
  the prompt is missing.
- **It treats "cross-tenant anomaly priors" as a detection tool for velocity/
  takeover.** Tell the model what RFC 009 actually is (statistical incident-rate
  priors, 5 fields, no sub-day timing, no velocity) so it doesn't credit KIFF
  with behavioral anomaly detection it lacks.
- **It omits the tenancy/scale question entirely** despite §6 asking about a
  "platform vendor governing many merchants." Add: *the cloud is schema-per-
  tenant with no vendor/sub-tenant hierarchy today — evaluate whether the multi-
  store framing is even expressible, and what new tenancy primitive it needs.*
- **It omits metering/economics.** Add: *every governed call is metered/billed
  and quota-limited; evaluate which subset of platform actions is economically
  governable vs the full stream.* A skeptic should hit this immediately and the
  prompt currently lets the model skip it.
- **Minor:** "fail-safe on unknowns" is correct and worth keeping, but tie it to
  the real rule (RFC 017: any outcome ≠ `allowed` withholds; unknown outcomes
  withhold by construction — invariant E4). That's a genuine strength to test
  the merchant-trust objection against.

---

### §5 — Platform seam table corrections

I can't source-verify upstream hook contracts any better than you can from here,
and you've correctly flagged that every enforce claim needs that verification per
the guard repo's own rule. So I won't assert hook names. Two **structural**
corrections from the cloud side, independent of upstream docs:

- The table's "enforce viable" cells are all gated on a constraint the table
  doesn't show: **enforce requires a synchronous seam that can block AND the
  decide round-trip fits the platform's request budget.** A WooCommerce
  `before`-hook that calls `decide` adds a network hop to the merchant's
  checkout/refund path; if the cloud is slow or down, fail-safe means
  *withholding the merchant's own legitimate action*. So "enforce viable"
  should read "enforce viable **if** the merchant accepts an external
  synchronous dependency in their action path" — many won't, which pushes even
  the self-hosted PHP platforms toward observe-first regardless of hook
  availability. The seam existing ≠ the merchant tolerating it.
- The Shopify row is the most honest and is right: SaaS, no native pre-emption
  of human admin actions, webhooks for observe. But add that Shopify's webhooks
  are **post-event** (orders/refunds fire *after* the action), so Shopify is
  **observe-only structurally** — which, per Q1/Q4, means no pre-execution
  receipt. Shopify is the platform where the RFC's value claim is weakest, and
  it's likely the largest merchant population. Worth saying out loud.

Net: the table is a reasonable *structural* first pass; reclassify the posture
column as "observe-first everywhere; enforce only where a blocking seam exists
*and* the merchant accepts an external dependency in-path," and mark Shopify as
post-event/observe-only.

### §6 — Global-vs-thin-shim split corrections

The split is mostly right but lists things on the "lives once, centrally" side
that **don't exist centrally yet**:

- "**multi-tenant authority (callers cannot self-approve)**" — the boundary is
  real and central, but "multi-tenant *authority* for many merchant stores under
  one vendor" is **not** built (Q5). Move "vendor-scoped multi-tenant authority"
  to a "**must be built**" column.
- "**attested receipts**" — central, yes, but execution-time + testnet + Draft
  (Q4). Keep it central but annotate "enforce-mode only, anchoring not at prod
  form."
- "**cross-tenant anomaly priors**" — listing this as a present central
  capability is the table's biggest error. It's Draft-with-kill-criteria and not
  a detector. Move to "**speculative / may not ship**."
- "**the action catalog**" — the catalog is *derived per tenant* by the guard's
  observe/`export_yaml`, then authored into that tenant's domain. There is no
  central commerce catalog. This is a per-tenant artifact today, not a central
  one; the "reusable commerce template" (Q6) is the thing that *could* be
  central, and it's only partially built (RFC 016, unbuilt).

What genuinely lives once, centrally, today: the **decide contract** (frozen,
RFC 017), the **per-tenant domain/state-machine engine** (RFC 001), the
**schema-isolated audit trail** (RFC 003), the **execution-receipt builder**
(RFC 008 code, behind the testnet caveat), and the **dashboard**. The thin
per-platform emitter description is correct and matches the guard adapter
discipline — no notes there.

---

### What the proposer couldn't see from the kiff-guard repo

- **The decide contract is frozen and additive-only (RFC 017).** You can rely on
  `{entity_id, entity_type, action_name, actor_id, parameters}` → outcome not
  changing under you within `/v1`. Critically: **`roles` is rejected from the
  body** — do not try to send merchant-actor roles on the call; authority must be
  provisioned as the key's roles against the tenant's domain. And the
  **unknown-outcome ⇒ withhold** guarantee (E4) is what lets the cloud add a
  future `quarantined`/`rate_limited` outcome without breaking your emitters —
  build the commerce emitter to withhold on anything ≠ `allowed`.
- **Receipts are metered and priced per-artifact (RFC 008) / per-control
  (RFC 018).** The cloud's commercial unit is a *small number of high-value
  protected controls*, not a stream. This directly constrains the commerce
  design: govern the consequential money-moving actions (refund, payout, price
  override), not every platform event.
- **The instrument-first sequencing (RFC 014) already endorses your observe-
  first instinct** — but it's framed as "observe to *derive the domain*, then a
  human ratifies risk/approval, then enforce." Observe is the on-ramp to
  authoring, not the terminal product. Your §4 "observe-first everywhere" aligns;
  just inherit RFC 014's honest limit: observe derives the *catalog and parameter
  shapes* only — **state machine, risk levels, and approval policy are human
  judgment, not inferable** from an action stream. A commerce domain still needs
  someone to declare "refund is only legal from PAID, high-risk, approval-
  required." The platform can't auto-generate that safely.
- **Anchoring is testnet (RFC 007 production form unbuilt); RFC 009 is the
  riskiest doc in the tree and may be rejected outright.** Don't let the discovery
  prompt or the RFC lean on either as present.
- **Tenancy is flat (RFC 003).** The multi-store-vendor story needs a new tenancy
  primitive — flag it as a dependency, not an assumption.
- **There's a live, working reference for the enforce path you should study:**
  the cloud's own `/dashboard/controls` "Control Proof" flow (RFC 018) does
  exactly the single-tenant, few-controls, enforce-mode, receipt-at-the-end loop
  this RFC wants — duplicate-payment is the worked example. The commerce RFC is
  essentially "RFC 018's Control Proof, with the emitter being a commerce
  platform instead of an agent guard." Framing it that way (rather than as a new
  out-of-band detection product) lands it squarely on primitives that exist.

### One-line recommendation

Reframe the RFC around **enforce-mode Control Proof for a curated set of money-
moving commerce actions on a single merchant tenant** (shippable on today's
primitives, matches RFC 018), and explicitly mark the **out-of-band detection**,
**behavioral-anomaly**, and **platform-vendor fleet** layers as *dependent on
unbuilt cloud work* (observe-mode receipts, a detection capability RFC 009 is not,
and a vendor tenancy primitive). The hypothesis's spine — actor-incidental,
mechanics-not-semantics, actions-as-structured-inputs — is sound and the cloud
was literally designed for it. The risk is shipping the *independent/out-of-band*
adjective as if the receipt's "before the money moved" guarantee survives it. It
doesn't, in observe mode. Be precise about that and the RFC gets much stronger.

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
