# custom-agent-http

**Govern a tool call from any stack — no SDK, no adapter, one HTTP POST.**

kiff-guard ships SDKs for Python and TypeScript, but the guard's job in
enforce mode is just one request: ask KIFF to decide before a tool runs.
If your agent is in Ruby, Go, Rust, shell, or anything else, you don't
need an SDK — you need this one call.

> A proposal is one `POST /v1/proposals/decide`. `allowed` → run the
> tool. Anything else (including an outcome this doc never mentioned) →
> withhold. That negation is the whole fail-safe.

## The contract

```
POST https://api.kiff.dev/v1/proposals/decide
Authorization: Bearer kiff_live_<tenant>_<random>
Content-Type: application/json

{
  "entity_id":   "ord_123",        // the thing being acted on
  "entity_type": "Order",          // its type in your KIFF domain
  "action_name": "REFUND_ORDER",   // the action your domain declares
  "actor_id":    "support-agent",  // who is acting (NOT its authority)
  "parameters":  { "amount_cents": 5000, "reason": "duplicate" }
}
```

Response:

```json
{
  "proposal_id": "prop_...",
  "outcome": "allowed",
  "reasons": [],
  "message": ""
}
```

Two rules, both load-bearing:

1. **Fail safe.** Run the tool only when `outcome == "allowed"`. Treat
   every other value — `approval_required`, `blocked`, `invalid`,
   `limit_exceeded`, *and any future outcome you've never seen* — as
   withhold. Gate on "not allowed", never on a hardcoded block-list, so a
   new cloud outcome can't slip an ungoverned action through.
2. **Never send roles.** Send `actor_id` (who is acting), never the
   actor's authority. The API key's roles govern server-side; a caller
   that could self-assert roles could self-grant clearance. Your only job
   is authenticating *which* caller this is, not what it's allowed to do.

This is the hosted/operate-nothing path: you call `api.kiff.dev`, KIFF
decides, you run nothing of KIFF's. (Don't confuse this with the KIFF
*framework's* `httpapi` validate route — that's a different, self-hosted
surface. kiff-guard users are on `/v1/proposals/decide`.)

## Run it (shell)

```bash
cd cookbook/custom-agent-http
export KIFF_CLOUD_API_KEY=kiff_live_...
./decide.sh ord_123 Order REFUND_ORDER
```

`decide.sh` POSTs the proposal and exits 0 only when the outcome is
`allowed` — so it drops straight into a shell agent:

```bash
if ./decide.sh "$ORDER" Order REFUND_ORDER; then
  ./refund.sh "$ORDER"          # allowed → run the tool
else
  echo "withheld; not running refund"
fi
```

## Run it (Go)

```bash
cd cookbook/custom-agent-http
export KIFF_CLOUD_API_KEY=kiff_live_...
go run decide.go ord_123 Order REFUND_ORDER
```

`decide.go` is a ~70-line stdlib-only client: build the body, POST it,
withhold on anything that isn't `allowed`. Copy it into your agent and
replace `runTool` with your real side effect.

## What you'd see

```
$ ./decide.sh ord_123 Order REFUND_ORDER
→ POST /v1/proposals/decide  REFUND_ORDER on Order/ord_123
← allowed
RUN: refund_order on ord_123

$ ./decide.sh ord_123 Order REFUND_ORDER       # same order, second time
→ POST /v1/proposals/decide  REFUND_ORDER on Order/ord_123
← blocked: order already refunded
WITHHELD: not running refund_order
```

The first refund clears; the state forbids the second, so KIFF blocks it —
exactly what the SDK recipes show, with no SDK in the path.

## Files

```
custom-agent-http/
├── README.md
├── decide.sh    # POSTs a proposal; exit 0 iff outcome == allowed
└── decide.go    # the same, stdlib-only Go (copy into your agent)
```

## License

MIT. Reference implementation.
