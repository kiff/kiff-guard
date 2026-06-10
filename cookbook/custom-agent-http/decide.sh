#!/usr/bin/env bash
# decide.sh — ask KIFF to clear one action, from any shell, no SDK.
#
# A proposal is one POST /v1/proposals/decide. We exit 0 ONLY when the
# outcome is exactly "allowed", so this drops into an && chain:
#
#   ./decide.sh ord_123 Order REFUND_ORDER && ./refund.sh ord_123
#
# Fail-safe by construction: any non-"allowed" outcome — including one
# this script has never heard of — exits non-zero and withholds. We never
# send the actor's roles; the API key's roles govern server-side.
set -euo pipefail

ENTITY_ID="${1:?usage: decide.sh <entity_id> <entity_type> <action_name>}"
ENTITY_TYPE="${2:?usage: decide.sh <entity_id> <entity_type> <action_name>}"
ACTION_NAME="${3:?usage: decide.sh <entity_id> <entity_type> <action_name>}"

: "${KIFF_CLOUD_API_KEY:?set KIFF_CLOUD_API_KEY=kiff_live_...}"
BASE_URL="${KIFF_BASE_URL:-https://api.kiff.dev}"
ACTOR_ID="${KIFF_ACTOR_ID:-custom-agent}"

body=$(cat <<JSON
{
  "entity_id":   "${ENTITY_ID}",
  "entity_type": "${ENTITY_TYPE}",
  "action_name": "${ACTION_NAME}",
  "actor_id":    "${ACTOR_ID}",
  "parameters":  {}
}
JSON
)

echo "→ POST /v1/proposals/decide  ${ACTION_NAME} on ${ENTITY_TYPE}/${ENTITY_ID}" >&2

resp=$(curl -sS \
  -H "Authorization: Bearer ${KIFF_CLOUD_API_KEY}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "${body}" \
  "${BASE_URL}/v1/proposals/decide")

# Pull "outcome" without a JSON dependency. Empty/missing => withhold.
# The trailing newline keeps sed portable across platforms that skip a
# final line with no newline.
outcome=$(printf '%s\n' "${resp}" | sed -n 's/.*"outcome"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
message=$(printf '%s\n' "${resp}" | sed -n 's/.*"message"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')

if [ "${outcome}" = "allowed" ]; then
  echo "← allowed" >&2
  exit 0
fi

# Anything that is not exactly "allowed" withholds — the fail-safe rule.
echo "← ${outcome:-<no outcome>}${message:+: ${message}}" >&2
exit 1
