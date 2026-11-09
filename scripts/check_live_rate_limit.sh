#!/usr/bin/env bash
# Post-deploy check: confirms a client can't pick its own rate-limit
# identity. api/security.py's client_ip() prefers DigitalOcean's own
# Do-Connecting-Ip header (added by App Platform's ingress, which
# overwrites any value a client sent -- see that function's own
# docstring and the DigitalOcean docs it cites) and never reads
# X-Forwarded-For at all. This script sends a flood of requests with a
# different, fake value for each header in turn and checks whether the
# app's rate limiter was fooled into treating them as separate
# clients.
#
# Run this AFTER deploying, against the live base URL. Not something
# Claude should run against https://typingtwin.com itself -- see
# DEPLOY.md's post-deploy checks.
#
# Usage: scripts/check_live_rate_limit.sh <base-url>
#   scripts/check_live_rate_limit.sh https://typingtwin.com
#   scripts/check_live_rate_limit.sh http://127.0.0.1:8000   # local container
#
# <base-url> must be exactly the app's configured ALLOWED_ORIGIN
# (scheme + host [+ port], no path) -- it is sent verbatim as the
# Origin header, which api/security.py:require_matching_origin checks
# for an exact match.
#
# Uses only curl and standard shell tools, sends well under 100
# requests total, and resets the party it created when done.

set -euo pipefail

BASE_URL="${1:?usage: $0 <base-url>}"
BASE_URL="${BASE_URL%/}"
ORIGIN="$BASE_URL"
PARTY_URL="$BASE_URL/api/game/party"
RESET_URL="$BASE_URL/api/game/party/reset"

# Comfortably above the app's default game_rate_limit_max_attempts
# (20 per 60s window -- config.py) without assuming the live
# environment uses exactly that value. Two batches of this size plus
# setup/cleanup stays well under 100 requests.
BATCH_SIZE=35
RATE_LIMIT_WINDOW_SECONDS=60

COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

# POST /api/game/party is the cheapest state-changing, rate-limited
# endpoint: it needs no existing session or party (it creates one),
# unlike rename/delete/attempt/replay. Each call replaces the
# session's current party, so repeated calls don't accumulate players
# or attempts -- just the (harmless, auto-expiring) orphaned parties
# the game already expects from an abandoned tab.
post_create_party() {
  curl -sS -o /dev/null -w '%{http_code}' \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -X POST "$PARTY_URL" \
    -H "Origin: $ORIGIN" \
    -H "Content-Type: application/json" \
    -H "$1" \
    -d '{"level":"word"}'
}

# run_batch <header-name> <fake-ip-prefix> -- sends BATCH_SIZE
# requests, each with a different fake address for <header-name>
# (TEST-NET documentation ranges, RFC 5737 -- never a real address).
# Prints PASS if any response was 429 (the fake header was ignored for
# rate-limit bucketing), FAIL if none was (the flood got through).
run_batch() {
  local header_name="$1" fake_prefix="$2" code saw_429=0
  for ((i = 1; i <= BATCH_SIZE; i++)); do
    code="$(post_create_party "$header_name: ${fake_prefix}.$i")"
    if [[ "$code" == "429" ]]; then
      saw_429=1
      break
    fi
  done
  if [[ "$saw_429" == 1 ]]; then
    echo PASS
  else
    echo FAIL
  fi
}

echo "Target: $BASE_URL"
echo

echo "Checking Do-Connecting-Ip spoofing ($BATCH_SIZE requests, each a different fake IP)..."
do_connecting_ip_result="$(run_batch "Do-Connecting-Ip" "192.0.2")"
echo "Do-Connecting-Ip spoofing: $do_connecting_ip_result"
echo

echo "Checking X-Forwarded-For spoofing ($BATCH_SIZE requests, each a different fake IP)..."
x_forwarded_for_result="$(run_batch "X-Forwarded-For" "198.51.100")"
echo "X-Forwarded-For spoofing: $x_forwarded_for_result"
echo

echo "Cleaning up the test party..."
reset_code="$(curl -sS -o /dev/null -w '%{http_code}' \
  -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -X POST "$RESET_URL" \
  -H "Origin: $ORIGIN")"
if [[ "$reset_code" == "429" ]]; then
  echo "Reset was itself rate-limited (expected right after a flood) -- waiting out the window and retrying..."
  sleep "$RATE_LIMIT_WINDOW_SECONDS"
  reset_code="$(curl -sS -o /dev/null -w '%{http_code}' \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -X POST "$RESET_URL" \
    -H "Origin: $ORIGIN")"
fi
if [[ "$reset_code" == "204" ]]; then
  echo "Test party reset."
else
  echo "Couldn't reset the test party (HTTP $reset_code) -- it will expire on its own (GAME_IDLE_EXPIRY_SECONDS)."
fi

echo
echo "===================="
echo "Do-Connecting-Ip spoofing: $do_connecting_ip_result"
echo "X-Forwarded-For spoofing:  $x_forwarded_for_result"
echo "===================="

if [[ "$do_connecting_ip_result" == "PASS" && "$x_forwarded_for_result" == "PASS" ]]; then
  exit 0
fi
exit 1
