#!/usr/bin/env bash
set -euo pipefail

BROKER_LISTEN_ADDR="${BROKER_LISTEN_ADDR:-0.0.0.0:8080}"
BROKER_DB_PATH="${BROKER_DB_PATH:-/data/broker.sqlite}"
BROKER_RAW_RETENTION_DAYS="${BROKER_RAW_RETENTION_DAYS:-0}"

VIXXY_STATE_FILE="${VIXXY_STATE_FILE:-/data/vixxy_token_state.json}"
VIXXY_POLL_INTERVAL_MS="${VIXXY_POLL_INTERVAL_MS:-3000}"
VIXXY_JITTER_MS="${VIXXY_JITTER_MS:-250}"
VIXXY_HEARTBEAT_INTERVAL_SECS="${VIXXY_HEARTBEAT_INTERVAL_SECS:-30}"
INITIAL_ACCESS_TOKEN="${INITIAL_ACCESS_TOKEN:-${ACCESS_TOKEN:-}}"

mkdir -p /data

echo "[ENTRYPOINT] Starting data-broker on ${BROKER_LISTEN_ADDR} (DB=${BROKER_DB_PATH}, raw_retention_days=${BROKER_RAW_RETENTION_DAYS})..."
data-broker \
  --listen "${BROKER_LISTEN_ADDR}" \
  --db "${BROKER_DB_PATH}" \
  --raw-retention-days "${BROKER_RAW_RETENTION_DAYS}" &
BROKER_PID=$!

# Wait for data-broker to bind before connecting vixxy-poller
for _ in {1..20}; do
  if curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo "[ENTRYPOINT] Starting vixxy-poller (interval=${VIXXY_POLL_INTERVAL_MS}ms, state_file=${VIXXY_STATE_FILE})..."
POLLER_ARGS=(
  --broker-ws-url "ws://127.0.0.1:8080/ws/ingest"
  --state-file "${VIXXY_STATE_FILE}"
  --poll-interval-ms "${VIXXY_POLL_INTERVAL_MS}"
  --jitter-ms "${VIXXY_JITTER_MS}"
  --heartbeat-interval-secs "${VIXXY_HEARTBEAT_INTERVAL_SECS}"
)
if [[ -n "${INITIAL_ACCESS_TOKEN}" ]]; then
  POLLER_ARGS+=(--initial-access-token "${INITIAL_ACCESS_TOKEN}")
fi

vixxy-poller "${POLLER_ARGS[@]}" &
POLLER_PID=$!

cleanup() {
  echo "[ENTRYPOINT] Shutting down processes..."
  kill "${POLLER_PID}" "${BROKER_PID}" 2>/dev/null || true
  wait
}
trap cleanup SIGINT SIGTERM

wait -n "${BROKER_PID}" "${POLLER_PID}"
EXIT_CODE=$?
echo "[ENTRYPOINT] A supervised process exited with code ${EXIT_CODE}; shutting down container..."
cleanup
exit "${EXIT_CODE}"
