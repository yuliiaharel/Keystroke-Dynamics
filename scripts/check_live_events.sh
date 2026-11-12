#!/usr/bin/env bash
# Post-deploy check for live updates (docs/plans/active/ROOMS_PLAN.md
# Phase 2 section 3): confirms that the host's proxy passes the
# server-sent event stream through as it's written, rather than
# buffering it or cutting it off.
#
# It creates one room, opens its event stream, then changes the room
# every 30 seconds for 5 minutes. It passes only if:
#   - the stream opens and sends the room's version straight away
#   - every change arrives on the stream within 2 seconds
#   - the same connection is still open at the end
#   - ending the room is announced on the stream, which then closes
#
# Run this AFTER deploying, against the live base URL. Not something
# Claude should run against https://typingtwin.com itself.
#
# Usage: scripts/check_live_events.sh <base-url> [duration-seconds]
#   scripts/check_live_events.sh https://typingtwin.com
#   scripts/check_live_events.sh http://127.0.0.1:8000 40   # local, shorter
#
# <base-url> must be exactly the app's configured ALLOWED_ORIGIN
# (scheme + host [+ port], no path) -- it is sent verbatim as the
# Origin header, which api/security.py:require_matching_origin checks
# for an exact match.
#
# Uses only curl, perl (for millisecond timing), and standard shell
# tools. Sends about a dozen requests in total, well inside the
# game's rate limit, and ends the room it created.

set -euo pipefail

BASE_URL="${1:?usage: $0 <base-url> [duration-seconds]}"
BASE_URL="${BASE_URL%/}"
DURATION_SECONDS="${2:-300}"
ORIGIN="$BASE_URL"

CHANGE_EVERY_SECONDS=30
MAX_DELAY_MS=2000

WORK_DIR="$(mktemp -d)"
COOKIE_JAR="$WORK_DIR/cookies"
STREAM_OUT="$WORK_DIR/stream"
STREAM_HEADERS="$WORK_DIR/headers"
STREAM_PID=""
ROOM_OPEN=0

now_ms() { perl -MTime::HiRes=time -e 'printf "%d\n", time * 1000'; }

post() { # post <path> [json-body] -- prints the body, then the status on its own line
  local path="$1" body="${2:-}"
  if [[ -n "$body" ]]; then
    curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST "$BASE_URL$path" \
      -H "Origin: $ORIGIN" -H "Content-Type: application/json" -d "$body" -w '\n%{http_code}'
  else
    curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST "$BASE_URL$path" \
      -H "Origin: $ORIGIN" -w '\n%{http_code}'
  fi
}

cleanup() {
  if [[ -n "$STREAM_PID" ]]; then kill "$STREAM_PID" 2>/dev/null || true; fi
  if [[ "$ROOM_OPEN" == 1 ]]; then
    post /api/game/room/end >/dev/null 2>&1 ||
      echo "Couldn't end the test room -- it will expire on its own (GAME_IDLE_EXPIRY_SECONDS)."
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

fail() {
  echo
  echo "FAIL: $1"
  if [[ -s "$STREAM_HEADERS" ]]; then
    echo "--- stream response headers ---"
    tr -d '\r' <"$STREAM_HEADERS"
  fi
  exit 1
}

stream_is_open() { [[ -n "$STREAM_PID" ]] && kill -0 "$STREAM_PID" 2>/dev/null; }

# wait_for_line <exact-line> <timeout-ms> -- prints how long it took, in ms
wait_for_line() {
  local line="$1" timeout_ms="$2" start
  start="$(now_ms)"
  while true; do
    if grep -qxF "$line" "$STREAM_OUT" 2>/dev/null; then
      echo $(($(now_ms) - start))
      return 0
    fi
    if (($(now_ms) - start > timeout_ms)); then return 1; fi
    sleep 0.05
  done
}

echo "Target: $BASE_URL (running for ${DURATION_SECONDS}s)"
echo

echo "Creating a test room..."
created="$(post /api/game/rooms '{"level":"sentence"}')"
[[ "${created##*$'\n'}" == "200" ]] || fail "couldn't create a room (HTTP ${created##*$'\n'})"
ROOM_OPEN=1

echo "Opening the event stream..."
curl -sS -N -b "$COOKIE_JAR" -D "$STREAM_HEADERS" -H "Accept: text/event-stream" \
  "$BASE_URL/api/game/room/events" >"$STREAM_OUT" 2>"$WORK_DIR/stream-errors" &
STREAM_PID=$!
STREAM_STARTED_MS="$(now_ms)"

first_ms="$(wait_for_line 'data: {"version":0}' 5000)" ||
  fail "the stream sent nothing within 5 seconds of opening -- a proxy is probably holding it back"
echo "First event after ${first_ms} ms."
echo "--- stream response headers ---"
tr -d '\r' <"$STREAM_HEADERS" | grep -i -E '^(HTTP/|content-type|cache-control|x-accel-buffering|cf-cache-status|content-encoding|transfer-encoding|via|server):' || true
echo

locked=true
version=0
changes=0
worst_ms=0
while true; do
  body="$(post /api/game/room/lock "{\"locked\":$locked}")"
  [[ "${body##*$'\n'}" == "200" ]] || fail "couldn't change the room (HTTP ${body##*$'\n'})"
  version=$((version + 1))
  delay_ms="$(wait_for_line "data: {\"version\":$version}" "$MAX_DELAY_MS")" ||
    fail "change $version did not arrive on the stream within ${MAX_DELAY_MS} ms"
  stream_is_open || fail "the stream closed after change $version"
  changes=$((changes + 1))
  if ((delay_ms > worst_ms)); then worst_ms=$delay_ms; fi
  elapsed_s=$((($(now_ms) - STREAM_STARTED_MS) / 1000))
  echo "  ${elapsed_s}s: change $version arrived after ${delay_ms} ms"
  if [[ "$locked" == true ]]; then locked=false; else locked=true; fi

  if ((elapsed_s >= DURATION_SECONDS)); then break; fi
  remaining=$((DURATION_SECONDS - elapsed_s))
  sleep "$((remaining < CHANGE_EVERY_SECONDS ? remaining : CHANGE_EVERY_SECONDS))"
  stream_is_open || fail "the stream closed while idle, ${elapsed_s}s to $((elapsed_s + CHANGE_EVERY_SECONDS))s in"
done

open_s=$((($(now_ms) - STREAM_STARTED_MS) / 1000))
heartbeats="$(grep -c '^: keep-alive' "$STREAM_OUT" || true)"
echo
echo "The one connection stayed open for ${open_s}s, with ${heartbeats} heartbeats."

echo "Ending the test room..."
ended="$(post /api/game/room/end)"
[[ "${ended##*$'\n'}" == "204" ]] || fail "couldn't end the room (HTTP ${ended##*$'\n'})"
ROOM_OPEN=0
wait_for_line 'data: {"ended":true}' "$MAX_DELAY_MS" >/dev/null ||
  fail "the stream never announced that the room ended"
closed=0
for _ in $(seq 1 40); do
  if ! stream_is_open; then
    closed=1
    break
  fi
  sleep 0.05
done
[[ "$closed" == 1 ]] || fail "the server left the stream open after the room ended"
STREAM_PID=""

echo
echo "===================="
echo "Events arrived within 2 seconds: PASS ($changes changes, slowest ${worst_ms} ms)"
echo "Connection survived ${open_s}s:      PASS"
echo "Room end announced and closed:   PASS"
echo "===================="
