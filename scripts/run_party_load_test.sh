#!/usr/bin/env bash
# docs/plans/done/PARTY_LAUNCH_PLAN.md Part 1's Done-when check: "A short load test
# against a container limited to 512 MiB, with 100 parties at the
# player limit, stays within memory. Show peak memory."
#
# Builds the real app image, runs it in a container capped at
# 512 MiB with no database, drives scripts/load_test_party.py
# against it, then reads the container's own cgroup peak-memory
# counter (memory.peak) -- the kernel's own historical high-water
# mark, not a poll-and-hope-we-caught-the-spike sample.
#
# docs/plans/active/ROOMS_PLAN.md Phase 2 extends it: "The 512 MiB load
# test, extended to 300 open streams across 50 rooms, stays within
# memory." The first [stream-rooms] parties each get a second browser,
# and both hold 3 live-update streams open (50 x 2 x 3 = 300) while
# the peak is read.
#
# Usage: scripts/run_party_load_test.sh [parties] [players-per-party] [stream-rooms]
set -euo pipefail
cd "$(dirname "$0")/.."

PARTIES="${1:-100}"
PLAYERS_PER_PARTY="${2:-12}"
STREAM_ROOMS="${3:-50}"
IMAGE_TAG="keystroke-dynamics-load-test"
CONTAINER_NAME="keystroke-dynamics-load-test"
PORT=18000

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Building the app image..."
docker build -t "$IMAGE_TAG" . >/dev/null

echo "Starting a 512 MiB container, no database, no account system..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER_NAME" \
  --memory=512m \
  -p "127.0.0.1:${PORT}:8000" \
  -e DEBUG=true \
  -e ENABLE_ACCOUNTS=false \
  -e ALLOWED_ORIGIN="http://127.0.0.1:${PORT}" \
  -e GAME_PARTY_LIMIT=500 \
  -e GAME_PLAYERS_PER_PARTY_LIMIT="$PLAYERS_PER_PARTY" \
  -e GAME_RATE_LIMIT_MAX_ATTEMPTS=100000 \
  -e GAME_RATE_LIMIT_WINDOW_SECONDS=60.0 \
  -e GAME_JOIN_RATE_LIMIT_MAX_ATTEMPTS=100000 \
  "$IMAGE_TAG" >/dev/null
# GAME_RATE_LIMIT_MAX_ATTEMPTS (and the join limit, for the second
# browser each streaming room gets) is raised for this load test's own
# traffic ONLY (it all comes from one client IP, unlike a real
# party's load) -- the shipped default (20/60s, config.py) is
# unaffected; same documented pattern as frontend/README.md's e2e
# RATE_LIMIT_MAX_ATTEMPTS override for the account system.

echo "Waiting for the app to come up..."
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null

echo "Baseline memory before the load test:"
docker exec "$CONTAINER_NAME" cat /sys/fs/cgroup/memory.current 2>/dev/null \
  || echo "(cgroup v2 memory.current not readable -- see memory.peak check below)"

echo
echo "Running the load test: ${PARTIES} parties x ${PLAYERS_PER_PARTY} players, streams in ${STREAM_ROOMS} of them..."
uv run python3 scripts/load_test_party.py \
  --base-url "http://127.0.0.1:${PORT}" \
  --parties "$PARTIES" \
  --players-per-party "$PLAYERS_PER_PARTY" \
  --stream-rooms "$STREAM_ROOMS"

echo
echo -n "Health check immediately after the load: "
curl -sf "http://127.0.0.1:${PORT}/health" && echo " -- still serving requests"

echo
echo "Container status after the load test:"
docker ps --filter "name=${CONTAINER_NAME}" --format '{{.Status}}'

echo
echo "Peak memory (cgroup memory.peak -- the kernel's own high-water mark):"
if docker exec "$CONTAINER_NAME" test -r /sys/fs/cgroup/memory.peak 2>/dev/null; then
  peak_bytes=$(docker exec "$CONTAINER_NAME" cat /sys/fs/cgroup/memory.peak)
  echo "${peak_bytes} bytes ($(awk -v b="$peak_bytes" 'BEGIN { printf "%.1f MiB", b / 1048576 }'))"
else
  echo "cgroup v2 memory.peak not available in this container -- falling back to docker stats:"
  docker stats "$CONTAINER_NAME" --no-stream
fi

echo
echo "Current memory and limit:"
docker stats "$CONTAINER_NAME" --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' \
  || echo "(container no longer running -- likely OOM-killed)"
