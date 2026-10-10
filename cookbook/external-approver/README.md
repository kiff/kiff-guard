# External approver for a KIFF Card

A separately operated service answers requests held by an Ask Card. KIFF checks
its bounded grant; the worker's normal MCP collection executes the approved
call. This connector holds no worker key, tool credential or admin session.
Python 3.9+ is sufficient; there are no dependencies. Docker is optional.

## 1. Grant access in KIFF

Open [Cards](https://app.kiff.dev/cards), choose an active Card, and expand
**External approver → Connect an external approver**. The Card must use Ask and
have a per-action amount limit. Choose a name, its worker/action, a maximum
amount and an expiry (up to 90 days). Only an active admin can grant access.
Human-only separation of duties prevents external grants.

Copy the `kiff_approver_…` credential shown once. Keep it in the separate service,
never in the worker's prompt or environment. Lost it? Revoke that connection and
create another. The grant cannot add budget, revise the Card or execute a tool.

## 2. Run the example

```sh
git clone https://github.com/kiff/kiff-guard.git
cd kiff-guard/cookbook/external-approver
cp connector.example.json connector.json
cp refund-policy.example.json refund-policy.json
```

Edit `connector.json` to set `context_file` to `refund-policy.json`. Adapt the
policy to your connected action, amount parameter and target argument. Amounts
in the policy file use the tool's **stored integer units**: 10000 means €100
when the tool declares EUR with scale 2. The example's `amount_eur` uses whole
euros (scale 0). Give the grant a ceiling above the Card's ordinary per-action
threshold, while retaining its cumulative budget.

The included synthetic facts let `synthetic-order-1` be refunded up to 100 stored
units; `synthetic-order-2` is not refundable. Other targets defer. In real use,
replace these fixtures with independently authenticated business facts. Never
copy the worker's claims into this trusted file.

Enter the credential without placing it in shell history:

```sh
read -r -s KIFF_APPROVER_KEY
export KIFF_APPROVER_KEY
python3 connector.py --config connector.json
```

It polls every 15 seconds. After the first successful poll, reload the Card:
**Awaiting connection** becomes **Connected**. More than two minutes without a
successful poll shows **Not responding**. This proves API contact, not model
health or an execution guarantee. Ctrl-C stops the service. Use your usual
process supervisor to keep it running; KIFF does not host it.

To process one batch and exit:

```sh
python3 connector.py --config connector.json --once
```

Now have the worker make an MCP call above its Card's per-action threshold and
inside the grant, using the synthetic target. The connector answers it. The
worker/plugin collects the approved call using `kiff_pending` and the same
arguments/operation id. KIFF rechecks all Card budgets; the tool runs once.

On **Needs you**, open the request to see the service's name, decision, reason
and the separately recorded tool outcome. Approval alone does not mean it ran.
Stop the connector or call a target outside its policy: the request stays
available for human review within the original deadline. An out-of-grant call
is never listed for this connector. Revoke the connection from the Card to
withdraw unused approvals; actions already executed remain historical.

## Optional model providers

Set `provider` to `jev` and supply `TYPESAFE_API_KEY` through your secret manager,
or set it to `strands` and add `strands_url` pointing to your separately running
Decider's `/v1/systemone`. Keep `context_file`: the model needs trusted policy
and facts separate from request content. Model errors or malformed answers
defer to a person; confidence never widens authority.

**Model integration is unverified.** The mappings follow the published
[Jev API](https://docs.typesafe.ai/api) and
[Strands Decider contract](https://github.com/strands-labs/strands-decider), but
no credentialed model call has been validated. Deterministic connector and
synthetic MCP validation are documented in the Cloud release PR. Do not treat
these mappings as a tested model integration.

## Optional Docker

```sh
docker build -t kiff-external-approver .
docker run --rm --read-only --cap-drop=ALL --security-opt=no-new-privileges \
  --env KIFF_APPROVER_KEY \
  --mount type=bind,src="$(pwd)",dst=/config,readonly \
  kiff-external-approver
```

For Jev, pass `--env TYPESAFE_API_KEY` too. Mount only the intended config/facts
in production. No Docker socket, inbound port or worker credentials are needed.
The container example has not been validated unless the release evidence says
otherwise; the plain Python command is the supported runnable path.

## Interoperability contract

A signed-in admin creates `POST /v1/me/approver-grants` with `name`, `card_id`,
`worker`, `action`, `parameter`, `max`, and RFC3339 `expires_at`. The principal is
generated when omitted. List status with `GET /v1/me/approver-grants?card_id=…`;
revoke with `POST /v1/me/approver-grants/{id}/revoke`.

The dedicated credential only accesses:

- `GET /v1/approver/holds` — matching requests; a successful read records contact.
- `GET /v1/approver/holds/{id}` — current exact arguments, Card, grant and token.
- `POST /v1/approver/holds/{id}/answer` — `review_token`, `decision` (`approve`,
  `reject`, `defer`), required `reason_code`, optional `reason` and `model`.

The token binds the answer to the current held revision and Card. Duplicate
matching answers are idempotent. 409 means stale/answered/expired; reread, never
invent new authority. 403 means grant withdrawn, expired or no longer valid;
stop and contact its admin. Uncovered holds return 404. Read failure returns
503 and grants nothing. Original deadlines, cumulative ceilings, human review
and tenant isolation continue to apply. Only one worker/action/amount parameter
and one Card are supported per grant; overlapping uncovered authority requires
a person. The connector never supplies its own execution outcome.

```sh
python3 -m unittest -v test_connector.py
```
