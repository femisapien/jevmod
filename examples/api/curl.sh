#!/usr/bin/env bash
# Mint a tenant key with the admin token, then moderate two messages. Needs curl and python (no jq).
set -euo pipefail
URL="${JEVMOD_API_URL:-http://localhost:8080}"
: "${JEVMOD_ADMIN_TOKEN:?set JEVMOD_ADMIN_TOKEN to the value the API was started with}"

KEY=$(curl -sS --fail -X POST "$URL/v1/keys" \
  -H "Authorization: Bearer $JEVMOD_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"tenant":"example-curl","label":"curl.sh"}' \
  | python -c "import json, sys; print(json.load(sys.stdin)['api_key'])")

curl -sS --fail -X POST "$URL/v1/moderate" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"messages":[
    {"id":"a","text":"FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro","channel_topic":"gaming"},
    {"id":"b","text":"Anyone know if the patch fixed the inventory bug?","channel_topic":"gaming"}
  ]}' \
  | python -c "
import json, sys
for d in json.load(sys.stdin)['decisions']:
    print(d['message_id'], d['action'], d['category'], d['probability'])
"
