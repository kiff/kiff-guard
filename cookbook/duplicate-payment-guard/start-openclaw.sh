#!/bin/bash
# Build a derived OpenClaw image with the kiff-guard-demo plugin baked
# into the discovered extensions dir, then run it on the host network so
# it can reach kiff-decide (:8081) and ap-app (:8082) on localhost and
# expose the gateway on :18789.
set -e
RECIPE=/home/ec2-user/duplicate-payment-guard
CFG=/home/ec2-user/oc-config
SECRETS=/home/ec2-user/oc-secrets

# Load the OpenAI key + gateway token from the recipe .env
set -a; . "$RECIPE/.env"; set +a
: "${OPENCLAW_GATEWAY_TOKEN:?set OPENCLAW_GATEWAY_TOKEN in .env}"
: "${OPENAI_API_KEY:?set OPENAI_API_KEY in .env}"

# Build the derived image (plugin baked into /app/dist/extensions).
echo "building kiff-cookbook-openclaw:local ..."
docker build -t kiff-cookbook-openclaw:local -f "$RECIPE/openclaw/Dockerfile" "$RECIPE"

mkdir -p "$CFG/workspace" "$SECRETS"
cp "$RECIPE/openclaw/openclaw.json" "$CFG/openclaw.json"

# Container runs as uid 1000 (node); make the config/secret mounts writable.
sudo chown -R 1000:1000 "$CFG" "$SECRETS"

docker rm -f openclaw 2>/dev/null || true
docker run -d --name openclaw \
  --network host \
  -e OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_GATEWAY_TOKEN" \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e OPENCLAW_GATEWAY_BIND=lan \
  -e OPENCLAW_DISABLE_BONJOUR=1 \
  -e KIFF_BASE_URL="http://localhost:8081" \
  -e AP_APP_URL="http://localhost:8082" \
  -e KIFF_CLOUD_API_KEY="${KIFF_CLOUD_API_KEY:-}" \
  -e KIFF_CLOUD_API_URL="${KIFF_CLOUD_API_URL:-https://api.kiff.dev}" \
  -e KIFF_CLOUD_PROJECT="${KIFF_CLOUD_PROJECT:-cookbook}" \
  -e KIFF_CLOUD_ENVIRONMENT="${KIFF_CLOUD_ENVIRONMENT:-aws}" \
  -e KIFF_CLOUD_WORKFLOW="${KIFF_CLOUD_WORKFLOW:-duplicate-payment}" \
  -v "$CFG:/home/node/.openclaw" \
  -v "$SECRETS:/home/node/.config/openclaw" \
  kiff-cookbook-openclaw:local \
  node dist/index.js gateway run

echo "openclaw container started; waiting for health..."
for i in $(seq 1 30); do
  if node -e "fetch('http://localhost:18789/healthz').then(r=>{if(r.ok)process.exit(0);process.exit(1)}).catch(()=>process.exit(1))" 2>/dev/null; then
    echo "HEALTHY"; exit 0
  fi
  sleep 2
done
echo "NOT healthy after 60s; logs:"; docker logs --tail 40 openclaw
exit 1
