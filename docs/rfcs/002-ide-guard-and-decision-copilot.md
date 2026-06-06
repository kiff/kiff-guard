# RFC (guard) 002 — IDE guard + decision copilot

**Status:** Draft — design sketch, not yet scheduled
**Date:** 2026-06-05
**Author:** kiff-guard agent (SDK side)
**Tracks affected:** guard SDK (a new IDE adapter), a separate optional
explainer layer (NOT the guard)

> **Scope discipline.** This RFC describes only kiff-guard's public surface
> (an IDE adapter that votes on tool calls) and a *separate* advisory layer
> that consumes the guard's verdict. It deliberately contains **no cloud
> internals** (no tenancy/metering/RFC numbers/contract addresses). Keep it
> that way.

---

## 0. Problem

AI coding IDEs (Kiro, this IDE, Cursor, Claude Code, …) let a model propose
and run tool calls — `fs_write`, `execute_bash`, `delete_file`, `git push`.
Two real gaps for the human in the loop:

1. **No consistent, auditable verdict before you hit "play."** The IDE's
   built-in allowlist is per-user, local, and stateless. There's no durable
   record of what the agent actually did across sessions, and no shared
   org-wide policy.
2. **No impact explanation when the agent offers options.** When the agent
   says "I can do A, B, or C," the user today copy-pastes the agent's reply
   into Claude/ChatGPT to understand the tradeoffs and risks before
   choosing. That loop is manual and invisible.

These are **two different problems** and they want **two different layers**.
Conflating them is the trap.

## 1. The two layers (and why they stay separate)

| Layer | What it answers | Engine | Property it must keep |
|---|---|---|---|
| **IDE guard** (KIFF) | "May this tool call run, given policy + state?" | deterministic state machine | small, auditable, never hallucinates, one receipt per call |
| **Decision copilot** (separate) | "What does each option mean, and what's the risk of each?" | an LLM | interpretive, natural-language, advisory only |

KIFF must **not** grow an LLM inside it — the whole reason the guard is
trustworthy is that it's deterministic and readable in a weekend (per the
KIFF whitepaper: "not a model gateway, not an agent framework"). The
copilot must **not** be the thing that blocks — an LLM's opinion is not an
authority decision. They compose; they do not merge.

```
agent proposes a tool call (or options A/B/C)
        │
        ├──► IDE guard (KIFF, deterministic):
        │        verdict per call: allowed | approval_required | blocked
        │        + reason (policy) + one audit receipt
        │
        └──► decision copilot (LLM, interpretive, OPTIONAL):
                 reads the proposed call(s) + KIFF's verdict(s)
                 renders "what each does, what it costs, which is safer"
        │
        ▼
   IDE UI: paint the play button green / amber / red (KIFF's verdict),
           show the copilot's plain-language impact inline.
```

The copilot is strictly better *with* KIFF underneath: KIFF gives it
**ground truth it cannot hallucinate** ("A is blocked, full stop") and a
record; the copilot gives the human the tradeoff narrative KIFF refuses to
invent.

## 2. Part A — the IDE guard (this is real KIFF work)

### 2.1 The seam

Enforce requires a **synchronous pre-tool-execution hook** that can veto the
call. Availability per IDE (source-verify before building each):

| IDE | Pre-tool seam | Enforce? | Notes |
|---|---|---|---|
| Kiro | `preToolUse` agent hook (filter by tool category read/write/shell, or regex for MCP) | yes | closest native fit; hook can deny the call |
| This IDE | `preToolUse` / `postToolUse` hooks | yes | same approach as Kiro |
| Claude Code | pre-tool hook (verify against current docs) | likely | source-verify |
| Cursor | built-in allowlist/auto-run only; no public per-call vote hook today | no (enforce) | observe via logs only until a hook exists |

The honest constraint: **no synchronous veto seam → no enforce.** Where a
seam is missing you can still *observe* (tail logs / post-hoc events) for the
audit trail, but you can't paint the button red before the fact.

### 2.2 Two integration routes (Kiro, as the first target)

**Route 1 — hook → command (no SDK code):** a `preToolUse` hook of type
`runCommand` that runs a tiny script: POST the pending `{tool, args}` to a
KIFF decide endpoint, exit non-zero to block. Kiro's hook contract already
treats a denied result as "tool call not allowed." This is a real enforce
gate with almost no code — the script *is* the adapter. Fastest way to try
observe-mode auditing today.

**Route 2 — a proper SDK adapter (`kiff_guard.adapters.kiro`):** vote shape,
same pattern as Strands/Hermes. Translate Kiro's `preToolUse` payload into
`decide_only`, block on `decision.withheld`, record exactly one receipt.
Gets the conformance driver + dedicated test file + CI job like every other
adapter. This is the durable version.

### 2.3 Mapping a coding tool call onto KIFF

```
execute_bash(command="git push --force origin main")
  -> { entity_id: <repo or branch>, entity_type: "Repo",
       action_name: "GIT_FORCE_PUSH", parameters: {target: "main"} }
fs_write(path=".env", ...)
  -> { entity_id: <repo>, entity_type: "Repo",
       action_name: "WRITE_PROTECTED_PATH", parameters: {path: ".env"} }
```

Honest note on the state-machine fit: most coding actions are **not**
lifecycle transitions ("edit file" isn't PAID→REFUNDED). So the IDE guard
mostly uses KIFF's **permission / risk / approval** parts, not the state
machine — *except* for genuinely stateful cases that an IDE allowlist
**cannot** express, which are the high-value ones:

- **release freeze**: repo entity in state `FROZEN` → all writes/pushes blocked.
- **file under review**: entity `UNDER_REVIEW` → no edits until approved.
- **protected paths/actions**: `.env`, secrets, CI config, IaC, `prod/*`;
  `git push` to main, `rm -rf`, DB drops, force-push — one **org policy**,
  decided server-side, same for every engineer, with an audit trail.

### 2.4 Latency reality

A coding agent fires tool calls rapidly; in enforce every call is a decide
round-trip. Mitigation, and the recommended default: **gate only high-risk
tools** (writes to protected paths, shell, git push) and let reads pass
ungated. Observe mode adds no blocking latency at all.

## 3. Part B — the decision copilot (separate, optional, LLM-backed)

NOT part of the guard. A separate component (could live in a different repo /
package). Shape:

```
input:  the agent's proposed action(s) or options A/B/C
        + KIFF's verdict + reason for each (from Part A)
        + light repo context (diff, target paths)
engine: an LLM prompt that explains each option's effect, reversibility,
        blast radius, and recommends a default — grounded by KIFF's verdicts
output: plain-language impact per option, shown inline in the IDE
```

Why grounding on KIFF matters: the copilot can *explain* why A is risky, but
it must defer to KIFF on whether A is *allowed*. "Blocked" is not the
copilot's opinion to override. This is what stops the explainer from
confidently green-lighting something policy forbids.

This is arguably the bigger product (it automates the copy-paste-to-Claude
loop the user does today), but it's a **consumer** of the guard, not the
guard. It should be designed and shipped on its own track.

## 4. Where this is worth it / where it isn't

**Worth it**
- Cross-session, team-wide **audit trail** of what the AI did in the repo
  (observe — cheap, no account, immediate value).
- **Central protected-path / protected-action policy** (enforce) that a
  per-user IDE allowlist can't express as one org rule.
- **State-aware gates** (release freeze, under-review) the IDE can't model.
- Compliance evidence for AI-authored changes.

**Not worth it**
- If you only want "block scary commands" — the IDE's built-in allowlist is
  simpler and zero-latency. Don't add a round-trip for a stateless denylist.
- Latency-sensitive tight loops if you gate *every* call — gate high-risk
  tools only.
- If your actions have no meaningful state — you're using a subset of KIFF;
  a lighter allowlist may be the honest fit.

## 5. Recommended path

1. **Observe first, on Kiro, via Route 1** (hook → command → `Guard(mode=
   "observe")`). Zero account, zero blocking. Prove the audit trail is
   valuable before anything else.
2. **Enforce for a small high-risk tool set** (writes to protected paths,
   shell, git push) once the policy is worth it.
3. **Promote Route 1 to a real `adapters/kiro.py`** (Route 2) with
   conformance + tests + CI when it earns a place in the SDK.
4. **Decision copilot** on its own track, consuming Part A's verdicts. Do
   not put the LLM inside the guard.

## 6. Open questions

1. Kiro's `preToolUse` payload shape — exact fields for tool name + args +
   the deny mechanism. Source-verify before writing `adapters/kiro.py`.
2. What's the right `entity` for a coding action — repo? branch? file? The
   answer decides whether stateful gates (freeze/review) are expressible.
3. Does the IDE expose enough UI surface to paint the play button from a
   hook verdict, or is the verdict only available as allow/block (no color)?
4. Where does the decision copilot live — same repo as a clearly-separated
   optional package, or its own repo? (Leaning: its own, to keep the guard
   dependency-free and LLM-free.)

## 7. Non-goals

- Putting an LLM inside the guard. Never.
- Replacing the IDE's allowlist. We add audit + central policy + state, not
  a denylist.
- A Cursor enforce integration until Cursor exposes a per-call veto hook.
