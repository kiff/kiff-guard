# collections-promise-guard

A cookbook recipe proving KIFF stops a collections agent from contacting
a borrower after they have made a valid promise to pay — protecting the
lender from FDCPA (US) and CONC (UK) violations.

**Adapter**: Agno (`tool_hooks` middleware shape)

## The scenario

A borrower owes $750 and is delinquent. A collections agent contacts them
via SMS. The borrower makes a promise to pay by Friday. A retry loop (or
a second agent task) tries to contact the same borrower again — 4 more
times. Each contact attempt after the promise is a compliance violation.

**KIFF blocks the re-contact** because the case state advances from
DELINQUENT → PROMISE_ACTIVE after the promise is recorded. The
INITIATE_COLLECTIONS_CONTACT action is only allowed from DELINQUENT or
BROKEN states. While a valid promise is active, every contact attempt
returns `state_not_allowed`.

## Architecture

1. **kiff-decide** (Go): the KIFF gate with a collections domain
   (CollectionsCase: DELINQUENT → PROMISE_ACTIVE → FULFILLED | BROKEN)
2. **app/server.py** (Python stdlib): the system of record. `/contact` is
   deliberately non-idempotent — every call logs a contact attempt.
3. **agent/collections_agent.py**: real Agno agent (gpt-4o-mini) with
   `contact_borrower` tool guarded via `agno_hook(guard)`.
4. **driver/scenario.py**: proof script showing WITHOUT vs WITH KIFF.

## Run locally

```bash
# Terminal 1: build + start the gate
cd kiff-decide && go mod tidy && go build -o kiff-decide . && ./kiff-decide

# Terminal 2: start the collections app
cd app && python3 server.py

# Terminal 3: install deps and run the proof
python3 -m venv .venv && source .venv/bin/activate
pip install agno openai
cd driver && python3 scenario.py
```

## Connect to KIFF Cloud

Set `KIFF_CLOUD_API_KEY` and the guard registers as a live runtime in
your dashboard under:
- project: `cookbook`
- environment: `aws`
- workflow: `collections-promise`
- adapter: `agno`

## Expected output

```
==================================================================
  WITHOUT KIFF — ungoverned: agent contacts borrower repeatedly
==================================================================
case case-nokiff-... created: Alice owes $500
agent contacts borrower 5 times (even after promise)...
  contact 1: sent via sms (#1)
  contact 2: sent via sms (#2)
  [borrower made a promise to pay $500 on Friday]
  contact 3: sent via sms (#3)
  contact 4: sent via sms (#4)
  contact 5: sent via sms (#5)

  RESULT: 5 contacts made (3 AFTER the promise) — HARASSMENT RISK

==================================================================
  WITH KIFF — real agent + gate enforces the promise window
==================================================================
case case-kiff-... created + seeded: Bob owes $750, state=DELINQUENT
  Connected to KIFF Cloud: runtime=grt_...
agent (real gpt-4o-mini via Agno) contacts Bob...
  agent response: I have contacted the borrower on case ...
  [Bob promises to pay $750 by Friday]
  state: PROMISE_ACTIVE
agent tries to re-contact 4 more times...
  attempt 2: BLOCKED by KIFF (case is "PROMISE_ACTIVE" — a valid promise exists...)
  attempt 3: BLOCKED by KIFF (case is "PROMISE_ACTIVE" — a valid promise exists...)
  attempt 4: BLOCKED by KIFF (case is "PROMISE_ACTIVE" — a valid promise exists...)
  attempt 5: BLOCKED by KIFF (case is "PROMISE_ACTIVE" — a valid promise exists...)

  RESULT: 1 contact(s) made; 4 blocked while promise active

==================================================================
  VERDICT
==================================================================
  WITHOUT KIFF : 5 contacts (3 after promise)   FAIL — FDCPA/CONC violation risk
  WITH KIFF    : 1 contact(s), 4 blocked         PASS — promise window enforced

  PROOF: the real agent's first contact was legitimate. KIFF blocked
  every retry once a valid promise was active — no harassment, no violation.
```

## What's being proven

1. **The gate + app loop works**: WITHOUT KIFF = 5 contacts including 3 after
   a promise; WITH KIFF = 1 contact, 4 blocked.
2. **The real agent works**: a real gpt-4o-mini turn via Agno called
   `contact_borrower`, the `agno_hook` intercepted it, KIFF allowed it
   (state=DELINQUENT), and the contact was logged.
3. **The promise window is enforced**: after PROMISE_MADE is ingested,
   state=PROMISE_ACTIVE, and KIFF's `state_not_allowed` blocks every
   subsequent contact attempt — regardless of which agent or task sends it.
4. **KIFF Cloud visibility**: the runtime is registered and shows live
   in the dashboard with heartbeat.
