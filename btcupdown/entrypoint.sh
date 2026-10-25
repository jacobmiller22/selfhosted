#!/usr/bin/env bash
set -euo pipefail

BROKER_LISTEN_ADDR="${BROKER_LISTEN_ADDR:-0.0.0.0:8080}"
BROKER_DB_PATH="${BROKER_DB_PATH:-/data/broker.sqlite}"
BROKER_RAW_RETENTION_DAYS="${BROKER_RAW_RETENTION_DAYS:-0}"

ENGINE_ENABLE="${ENGINE_ENABLE:-true}"
ENGINE_LISTEN_ADDR="${ENGINE_LISTEN_ADDR:-0.0.0.0:8081}"
ENGINE_DB_PATH="${ENGINE_DB_PATH:-${BROKER_DB_PATH}}"
ENGINE_TRADE_LOG_PATH="${ENGINE_TRADE_LOG_PATH:-/data/trade_log.txt}"
ENGINE_BROKER_WS_URL="${ENGINE_BROKER_WS_URL:-ws://127.0.0.1:8080/ws}"
ENGINE_PARTICIPANT_ID="${ENGINE_PARTICIPANT_ID:-bjorn}"
ENGINE_START_BALANCE="${ENGINE_START_BALANCE:-100.0}"

VIXXY_STATE_FILE="${VIXXY_STATE_FILE:-/data/vixxy_token_state.json}"
VIXXY_POLL_INTERVAL_MS="${VIXXY_POLL_INTERVAL_MS:-3000}"
VIXXY_JITTER_MS="${VIXXY_JITTER_MS:-250}"
VIXXY_HEARTBEAT_INTERVAL_SECS="${VIXXY_HEARTBEAT_INTERVAL_SECS:-30}"
INITIAL_ACCESS_TOKEN="${INITIAL_ACCESS_TOKEN:-${ACCESS_TOKEN:-}}"

KALSHI_ENABLE="${KALSHI_ENABLE:-true}"
KALSHI_BASE_URL="${KALSHI_BASE_URL:-https://api.elections.kalshi.com/trade-api/v2}"
KALSHI_SERIES_TICKER="${KALSHI_SERIES_TICKER:-KXBTC15M}"
KALSHI_POLL_INTERVAL_MS="${KALSHI_POLL_INTERVAL_MS:-1000}"
KALSHI_SETTLE_POLL_INTERVAL_MS="${KALSHI_SETTLE_POLL_INTERVAL_MS:-2000}"
KALSHI_ENV_FILE="${KALSHI_ENV_FILE:-/data/kalshi.env}"

mkdir -p /data

if [[ -f "${KALSHI_ENV_FILE}" ]]; then
  echo "[ENTRYPOINT] Loading BYOC Kalshi credentials from ${KALSHI_ENV_FILE}..."
  set -a
  # shellcheck disable=SC1090
  source "${KALSHI_ENV_FILE}"
  set +a
fi

if [[ -n "${KALSHI_PRIVATE_KEY_PATH:-}" && ! -f "${KALSHI_PRIVATE_KEY_PATH}" && -f "/data/kalshi_private.pem" ]]; then
  export KALSHI_PRIVATE_KEY_PATH="/data/kalshi_private.pem"
fi

echo "[ENTRYPOINT] Starting data-broker on ${BROKER_LISTEN_ADDR} (DB=${BROKER_DB_PATH}, raw_retention_days=${BROKER_RAW_RETENTION_DAYS})..."
data-broker \
  --listen "${BROKER_LISTEN_ADDR}" \
  --db "${BROKER_DB_PATH}" \
  --raw-retention-days "${BROKER_RAW_RETENTION_DAYS}" &
BROKER_PID=$!

# Wait for data-broker to bind before connecting co-located engine & pollers
for _ in {1..120}; do
  if curl -fsS "http://127.0.0.1:8080/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

PIDS=("${BROKER_PID}")

if [[ "${ENGINE_ENABLE}" == "true" ]]; then
  echo "[ENTRYPOINT] Starting co-located btcupdown-engine on ${ENGINE_LISTEN_ADDR} (DB=${ENGINE_DB_PATH}, participant=${ENGINE_PARTICIPANT_ID})..."
  ENGINE_ARGS=(
    --url "${ENGINE_BROKER_WS_URL}"
    --db "${ENGINE_DB_PATH}"
    --bind "${ENGINE_LISTEN_ADDR}"
    --trade-log "${ENGINE_TRADE_LOG_PATH}"
    --start-balance "${ENGINE_START_BALANCE}"
    --kalshi-base-url "${KALSHI_BASE_URL}"
  )
  if [[ -n "${ENGINE_PARTICIPANT_ID}" ]]; then
    ENGINE_ARGS+=(--participant "${ENGINE_PARTICIPANT_ID}")
  fi
  if [[ -n "${KALSHI_KEY_ID:-}" ]]; then
    ENGINE_ARGS+=(--kalshi-key-id "${KALSHI_KEY_ID}")
  fi
  if [[ -n "${KALSHI_PRIVATE_KEY_PATH:-}" ]]; then
    ENGINE_ARGS+=(--kalshi-private-key-path "${KALSHI_PRIVATE_KEY_PATH}")
  fi
  btcupdown-engine "${ENGINE_ARGS[@]}" &
  ENGINE_PID=$!
  PIDS+=("${ENGINE_PID}")
fi

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
PIDS+=("${POLLER_PID}")

if [[ "${KALSHI_ENABLE}" == "true" ]]; then
  echo "[ENTRYPOINT] Starting kalshi-poller (series=${KALSHI_SERIES_TICKER}, interval=${KALSHI_POLL_INTERVAL_MS}ms)..."
  kalshi-poller \
    --broker-ws-url "ws://127.0.0.1:8080/ws/ingest" \
    --kalshi-base-url "${KALSHI_BASE_URL}" \
    --series-ticker "${KALSHI_SERIES_TICKER}" \
    --poll-interval-ms "${KALSHI_POLL_INTERVAL_MS}" \
    --settle-poll-interval-ms "${KALSHI_SETTLE_POLL_INTERVAL_MS}" &
  KALSHI_PID=$!
  PIDS+=("${KALSHI_PID}")
fi

cleanup() {
  echo "[ENTRYPOINT] Shutting down processes..."
  kill "${PIDS[@]}" 2>/dev/null || true
  wait
}
trap cleanup SIGINT SIGTERM

wait -n "${PIDS[@]}"
EXIT_CODE=$?
echo "[ENTRYPOINT] A supervised process exited with code ${EXIT_CODE}; shutting down container..."
cleanup
exit "${EXIT_CODE}"
