#!/usr/bin/env bash
#
# One command: start a real Switch stack (Postgres + switch-core + Mattermost +
# Gateway), then post one message from a Mattermost room and print its id.
#
# Run this INSIDE WSL2 (or any Linux host) that has Docker, with a Switch
# checkout at $SWITCH_DIR that already has a populated .env:
#
#   bash scripts/switch_local_proof.sh
#
# Environment overrides:
#   SWITCH_DIR              Switch checkout (default: /root/switch)
#   MATTERMOST_CHANNEL      room to post in (default: architecture-review)
#   MATTERMOST_HOST_PORT    Mattermost port (default: from .env, else 8065)
#
set -euo pipefail

SWITCH_DIR="${SWITCH_DIR:-/root/switch}"
COMPOSE_FILE="deploy/local/standalone-docker-compose.yml"
CHANNEL_NAME="${MATTERMOST_CHANNEL:-architecture-review}"
CHANNEL_DISPLAY="${MATTERMOST_CHANNEL_DISPLAY:-Architecture Review}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

command -v docker >/dev/null || die "docker not found (install Docker inside WSL2 first)"
command -v curl >/dev/null || die "curl not found"
command -v python3 >/dev/null || die "python3 not found"

[ -f "$SWITCH_DIR/.env" ] || die "no .env in $SWITCH_DIR (copy .env.example and run deploy/local/generate-env-secrets.sh)"
[ -f "$SWITCH_DIR/$COMPOSE_FILE" ] || die "missing $SWITCH_DIR/$COMPOSE_FILE"

cd "$SWITCH_DIR"
set -a; . ./.env; set +a
MM="http://127.0.0.1:${MATTERMOST_HOST_PORT:-8065}"

# --- bring the stack up -----------------------------------------------------
step "starting Switch (profiles: collab, gateway)"
docker compose --env-file .env -f "$COMPOSE_FILE" --profile collab --profile gateway up -d

step "waiting for Mattermost on $MM"
ready=0
for _ in $(seq 1 120); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "$MM/api/v4/system/ping" || true)" = "200" ]; then
    ready=1; break
  fi
  sleep 2
done
[ "$ready" = "1" ] || die "Mattermost did not become ready (check: docker compose logs mattermost)"

# --- helpers ----------------------------------------------------------------
# Mattermost returns the session token in the `Token` response header, and
# error payloads carry a string `id` too, so never treat a body id as a token.
login() {
  local user="$1" pass="$2" headers body
  headers=$(mktemp)
  body=$(mktemp)
  curl -s -D "$headers" -o "$body" -X POST "$MM/api/v4/users/login" \
    -H 'Content-Type: application/json' \
    -d "$(U="$user" P="$pass" python3 -c 'import json,os;print(json.dumps({"login_id":os.environ["U"],"password":os.environ["P"]}))')" || true
  tr -d '\r' < "$headers" | awk 'tolower($1)=="token:"{print $2}'
  rm -f "$headers" "$body"
}

# Print a JSON field only when the response is not an error object.
jget() {
  python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit
if isinstance(d, dict) and "status_code" not in d:
    print(d.get(sys.argv[1], ""))' "$1"
}

# --- log in ----------------------------------------------------------------
# The seeded admin account is the only one allowed to create the room; the
# regular `user` account is a team member for reading it in the UI.
step "logging in to Mattermost"
TOKEN=$(login "${MATTERMOST_ADMIN_USER:-admin}" "${MATTERMOST_ADMIN_PASSWORD:-}")
[ -n "$TOKEN" ] || die "admin login failed (check MATTERMOST_ADMIN_USER / MATTERMOST_ADMIN_PASSWORD in .env)"

TEAM_ID=$(curl -s -H "Authorization: Bearer $TOKEN" "$MM/api/v4/teams/name/${MATTERMOST_TEAM_NAME:-switch}" | jget id)
[ -n "$TEAM_ID" ] || die "team '${MATTERMOST_TEAM_NAME:-switch}' not found; wait for the setup container to finish"

# --- room ------------------------------------------------------------------
step "room #$CHANNEL_NAME"
CHANNEL_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$MM/api/v4/teams/$TEAM_ID/channels/name/$CHANNEL_NAME" | jget id)
if [ -z "$CHANNEL_ID" ]; then
  CHANNEL_ID=$(curl -s -X POST "$MM/api/v4/channels" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "$(NAME="$CHANNEL_NAME" DISPLAY="$CHANNEL_DISPLAY" TEAM="$TEAM_ID" python3 -c \
        'import json,os;print(json.dumps({"team_id":os.environ["TEAM"],"name":os.environ["NAME"],"display_name":os.environ["DISPLAY"],"type":"O"}))')" \
    | jget id)
  [ -n "$CHANNEL_ID" ] || die "could not create #$CHANNEL_NAME"
  echo "created #$CHANNEL_NAME ($CHANNEL_ID)"
else
  echo "using existing #$CHANNEL_NAME ($CHANNEL_ID)"
fi

# --- post ------------------------------------------------------------------
step "posting the decision message"
MESSAGE='**Decision:** Postgres 16 + TimescaleDB as the primary store for the telemetry pipeline.

**Trade-off:** dedicated vacuum tuning and partition management overhead.
**Alternative considered:** ClickHouse for raw ingest, rejected for now: no ClickHouse operations experience on the team.
**Rollback:** swap to ClickHouse behind the same writer interface if sustained write throughput exceeds 50k rows/s for two weeks.

Recorded from the #architecture-review debate by @architect (Switch ADR Architect).'

RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "$MM/api/v4/posts" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "$(M="$MESSAGE" C="$CHANNEL_ID" python3 -c 'import json,os;print(json.dumps({"channel_id":os.environ["C"],"message":os.environ["M"]}))')")
CODE=$(printf '%s' "$RESPONSE" | tail -n 1)
BODY=$(printf '%s' "$RESPONSE" | sed '$d')
POST_ID=$(printf '%s' "$BODY" | jget id)
[ "$CODE" = "201" ] && [ -n "$POST_ID" ] || die "post failed (HTTP $CODE): $(printf '%s' "$BODY" | head -c 300)"

# --- prove it landed -------------------------------------------------------
step "verifying"
curl -s -H "Authorization: Bearer $TOKEN" "$MM/api/v4/posts/$POST_ID" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "status_code" in d:
    raise SystemExit("post not readable back: %s" % d.get("message"))
print("channel:", d["channel_id"])
print("created_at(ms):", d["create_at"])
print("chars:", len(d["message"]))'

printf '\nposted: %s/%s/pl/%s\n' "$MM" "${MATTERMOST_TEAM_NAME:-switch}" "$POST_ID"
printf 'open the room: %s/%s/channels/%s\n' "$MM" "${MATTERMOST_TEAM_NAME:-switch}" "$CHANNEL_NAME"
