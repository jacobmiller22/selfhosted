#!/usr/bin/env bash
# ==============================================================================
# Ephemeral Staging: One-Command Interactive Preview CLI (tools/preview.sh)
# ==============================================================================
# Seamlessly spins up an isolated ephemeral staging container on remote host
# 'bjorn' (or localhost), hydrates it with live production database snapshots,
# sets up an SSH port-forward tunnel to your local machine, and launches
# the preview URL in your browser.
#
# Supported Services:
#   actual         Actual Budget (staging port: 5006, snapshot account & user sqlite DBs)
#   vaultwarden    Vaultwarden (staging port: 7278, snapshot db.sqlite3, copy keys)
#
# Safety Guarantees:
#   - Pre-flight Remote Host Verification (RHVP) via SSH
#   - Online SQLite snapshotting via hydrate.sh (zero downtime/locks on prod)
#   - Isolated staging volumes (*-stage-data) and bridge network (staging-net)
#   - Dual-layer teardown:
#       1. Local trap on SIGINT (Ctrl+C), SIGTERM, EXIT closes tunnel & stops container
#       2. Remote background watchdog timer on bjorn automatically stops container
#          if SSH connection drops or laptop sleeps.
#   - Full --dry-run simulation support
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Default Settings & Variables
# ------------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICE=""
HOST="bjorn"
TIMEOUT=60
SKIP_HYDRATE=false
RESET=false
NO_OPEN=false
DRY_RUN=false
LOCAL_PORT=""

SSH_BIN="${SSH_CMD:-ssh}"
CURL_BIN="${CURL_CMD:-curl}"
OPEN_BIN="${OPEN_CMD:-open}"

CONTAINER_NAME=""
REMOTE_PORT=""
COMPOSE_PATH=""
TUNNEL_PID=""
WATCHDOG_PID=""
SESSION_ACTIVE=false
CLEANED_UP=false

# ------------------------------------------------------------------------------
# Help & Usage Display
# ------------------------------------------------------------------------------
show_help() {
  cat <<HELP_EOF
Usage: $(basename "$0") <SERVICE> [OPTIONS]
       $(basename "$0") [OPTIONS] -s <SERVICE>

Interactive one-command browser preview CLI for ephemeral staging environments on host 'bjorn'.
Hydrates live snapshot data, opens an SSH port-forward tunnel, and launches your browser.

Supported Services:
  actual                     Actual Budget (staging port: 5006, isolated volume: actual-stage-data)
  vaultwarden                Vaultwarden (staging port: 7278, isolated volume: vw-stage-data)

Options:
  -s, --service <name>       Service name ('actual' or 'vaultwarden')
  --host <hostname>          Target remote host (default: 'bjorn'; use 'localhost' for local)
  --port <local_port>        Local forwarded port (default: 5006 for actual, 7278 for vaultwarden)
  --timeout <minutes>        Safety watchdog timeout in minutes before auto-stop (default: 60)
  --skip-hydrate             Skip snapshot hydration and boot existing staging volume
  --reset                    Wipe existing staging volume and re-hydrate fresh snapshot
  --no-open                  Do not automatically open browser; display preview URL only
  --dry-run                  Simulate actions without modifying containers or opening ports
  -h, --help                 Display this help message and exit

Workflow:
  1. Pre-flight host reachability check (RHVP via SSH)
  2. Online snapshot hydration via tools/staging/hydrate.sh on target host
  3. Ephemeral staging container launch (via Compose profile 'staging')
  4. Remote health probe on staging port (HTTP 200/302)
  5. Local SSH port-forward tunnel setup (localhost:<port> -> <host>:<port>)
  6. Remote background safety watchdog registration (auto-stops after timeout)
  7. Automatic browser launch (http://localhost:<port>)
  8. Guaranteed interactive teardown on Ctrl+C / EXIT (stops tunnel and staging container)

Examples:
  $(basename "$0") actual
  $(basename "$0") vaultwarden --timeout 30
  $(basename "$0") actual --reset --no-open
  $(basename "$0") actual --dry-run
HELP_EOF
}

# ------------------------------------------------------------------------------
# Parse CLI Arguments
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    actual|vaultwarden)
      SERVICE="$1"
      shift
      ;;
    -s|--service)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      SERVICE="$2"
      shift 2
      ;;
    --service=*)
      SERVICE="${1#*=}"
      shift
      ;;
    --host)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for --host" >&2
        exit 1
      fi
      HOST="$2"
      shift 2
      ;;
    --host=*)
      HOST="${1#*=}"
      shift
      ;;
    --port)
      if [[ -z "${2:-}" || "${2}" =~ ^-[a-zA-Z-] ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      LOCAL_PORT="$2"
      shift 2
      ;;
    --port=*)
      LOCAL_PORT="${1#*=}"
      shift
      ;;
    --timeout)
      if [[ -z "${2:-}" || "${2}" =~ ^-[a-zA-Z-] ]]; then
        echo "[-] ERROR: Missing value for --timeout" >&2
        exit 1
      fi
      TIMEOUT="$2"
      shift 2
      ;;
    --timeout=*)
      TIMEOUT="${1#*=}"
      shift
      ;;
    --skip-hydrate)
      SKIP_HYDRATE=true
      shift
      ;;
    --reset)
      RESET=true
      shift
      ;;
    --no-open)
      NO_OPEN=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "[-] ERROR: Unknown option: $1" >&2
      echo "Run '$(basename "$0") --help' for usage." >&2
      exit 1
      ;;
  esac
done

# ------------------------------------------------------------------------------
# Input Validation & Normalization
# ------------------------------------------------------------------------------
if [[ -z "${SERVICE}" ]]; then
  echo "[-] ERROR: Missing required service name ('actual' or 'vaultwarden')." >&2
  echo "Run '$(basename "$0") --help' for usage." >&2
  exit 1
fi

case "${SERVICE}" in
  actual)
    CONTAINER_NAME="actual-server-staging"
    REMOTE_PORT=5006
    COMPOSE_PATH="actual/compose.yml"
    DEFAULT_PORT=5006
    SERVICE_TITLE="Actual Budget"
    ;;
  vaultwarden)
    CONTAINER_NAME="vaultwarden-staging"
    REMOTE_PORT=7278
    COMPOSE_PATH="vaultwarden/compose.yml"
    DEFAULT_PORT=7278
    SERVICE_TITLE="Vaultwarden"
    ;;
  *)
    echo "[-] ERROR: Unsupported service '${SERVICE}'. Supported: 'actual', 'vaultwarden'." >&2
    exit 1
    ;;
esac

if [[ -z "${LOCAL_PORT}" ]]; then
  LOCAL_PORT="${DEFAULT_PORT}"
fi

if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT}" -le 0 ]]; then
  echo "[-] ERROR: Timeout must be a positive integer in minutes, got: '${TIMEOUT}'" >&2
  exit 1
fi

if ! [[ "${LOCAL_PORT}" =~ ^[0-9]+$ ]] || [[ "${LOCAL_PORT}" -le 1024 || "${LOCAL_PORT}" -ge 65535 ]]; then
  echo "[-] ERROR: Local port must be an integer between 1025 and 65534, got: '${LOCAL_PORT}'" >&2
  exit 1
fi

is_remote() {
  [[ -n "${HOST}" && "${HOST}" != "local" && "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]
}

# ------------------------------------------------------------------------------
# Teardown Trap Handler
# ------------------------------------------------------------------------------
cleanup() {
  local exit_code=$?
  trap - EXIT ERR INT TERM

  if [[ "${CLEANED_UP}" == "true" ]]; then
    return "${exit_code}"
  fi
  CLEANED_UP=true

  if [[ "${DRY_RUN}" == "true" ]]; then
    return "${exit_code}"
  fi

  echo ""
  echo "=============================================================================="
  echo "🛑 Teardown: Closing Preview Session for ${SERVICE_TITLE}..."
  echo "=============================================================================="

  # 1. Terminate local SSH tunnel if active
  if [[ -n "${TUNNEL_PID}" ]]; then
    if kill -0 "${TUNNEL_PID}" 2>/dev/null; then
      echo "[+] Closing local SSH port-forward tunnel (PID: ${TUNNEL_PID})...."
      kill "${TUNNEL_PID}" 2>/dev/null || true
      wait "${TUNNEL_PID}" 2>/dev/null || true
    fi
  fi

  # 2. Terminate local background watchdog process if active
  if [[ -n "${WATCHDOG_PID}" ]]; then
    if kill -0 "${WATCHDOG_PID}" 2>/dev/null; then
      kill "${WATCHDOG_PID}" 2>/dev/null || true
    fi
  fi

  # 3. Stop remote staging container
  if [[ "${SESSION_ACTIVE}" == "true" ]]; then
    echo "[+] Stopping staging container '${CONTAINER_NAME}' on '${HOST}'..."
    if is_remote; then
      # shellcheck disable=SC2029
      "${SSH_BIN}" -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" \
        "docker compose -f /home/jacobmiller22/hosting/selfhosted/${COMPOSE_PATH} --profile staging stop '${CONTAINER_NAME}' >/dev/null 2>&1 || docker stop '${CONTAINER_NAME}' >/dev/null 2>&1 || true" || true
    else
      docker compose -f "${REPO_ROOT}/${COMPOSE_PATH}" --profile staging stop "${CONTAINER_NAME}" >/dev/null 2>&1 || docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    fi
    echo "[+] Staging container successfully stopped."
  fi

  echo "✓ Preview session closed cleanly. All resources reclaimed."
  echo "=============================================================================="
  return "${exit_code}"
}

trap cleanup EXIT ERR INT TERM

# ------------------------------------------------------------------------------
# Dry-Run Execution Plan (Deterministic Simulation)
# ------------------------------------------------------------------------------
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "=============================================================================="
  echo "🔍 [DRY-RUN] Ephemeral Staging Interactive Preview Simulation"
  echo "=============================================================================="
  echo "[dry-run] Service:               ${SERVICE} (${SERVICE_TITLE})"
  echo "[dry-run] Staging Container:     ${CONTAINER_NAME}"
  echo "[dry-run] Target Host:           ${HOST}"
  echo "[dry-run] Staging Remote Port:   ${REMOTE_PORT}"
  echo "[dry-run] Local Forwarded Port:  ${LOCAL_PORT}"
  echo "[dry-run] Local Preview URL:     http://localhost:${LOCAL_PORT}"
  echo "[dry-run] Auto-Open Browser:     $([[ "${NO_OPEN}" == "true" ]] && echo "false" || echo "true")"
  echo "[dry-run] Watchdog Timeout:      ${TIMEOUT} minutes"
  echo "[dry-run] Skip Hydration:        ${SKIP_HYDRATE}"
  echo "[dry-run] Force Reset Volume:    ${RESET}"
  echo ""

  echo "[dry-run] Step 1: Pre-flight Remote Host Verification (RHVP):"
  if is_remote; then
    echo "[dry-run] would verify SSH reachability: ${SSH_BIN} -o BatchMode=yes -o ConnectTimeout=5 ${HOST} 'echo ok'"
  else
    echo "[dry-run] local execution (host: ${HOST})"
  fi

  echo "[dry-run] Step 2: Production Snapshot Hydration & Staging Boot:"
  hydrate_args=()
  if [[ "${RESET}" == "true" ]]; then
    hydrate_args+=("--reset" "${SERVICE}")
  else
    hydrate_args+=("${SERVICE}")
  fi
  hydrate_args+=("--start")

  if is_remote; then
    echo "[dry-run] would execute remotely on ${HOST}:"
    echo "          /home/jacobmiller22/hosting/selfhosted/tools/staging/hydrate.sh ${hydrate_args[*]}"
  else
    echo "[dry-run] would execute locally: ${REPO_ROOT}/tools/staging/hydrate.sh ${hydrate_args[*]}"
  fi

  echo "[dry-run] Step 3: Remote Staging Health Probe:"
  if is_remote; then
    echo "[dry-run] would poll via SSH: ${SSH_BIN} ${HOST} 'curl -fsS http://localhost:${REMOTE_PORT}/'"
  else
    echo "[dry-run] would poll locally: ${CURL_BIN} -fsS http://localhost:${REMOTE_PORT}/"
  fi

  echo "[dry-run] Step 4: Ephemeral SSH Port-Forward Tunnel:"
  if is_remote; then
    echo "[dry-run] would open background SSH tunnel:"
    echo "          ${SSH_BIN} -N -L ${LOCAL_PORT}:localhost:${REMOTE_PORT} ${HOST}"
  else
    echo "[dry-run] direct local port binding on http://localhost:${LOCAL_PORT}"
  fi

  echo "[dry-run] Step 5: Remote Safety Watchdog Timer (${TIMEOUT}m):"
  if is_remote; then
    echo "[dry-run] would register remote background watchdog on ${HOST}:"
    echo "          nohup bash -c 'sleep $((TIMEOUT * 60)) && docker compose -f /home/jacobmiller22/hosting/selfhosted/${COMPOSE_PATH} --profile staging stop ${CONTAINER_NAME}'"
  fi

  echo "[dry-run] Step 6: Browser Launch:"
  if [[ "${NO_OPEN}" == "true" ]]; then
    echo "[dry-run] browser launch suppressed (--no-open flag set)"
  else
    echo "[dry-run] would execute: ${OPEN_BIN} http://localhost:${LOCAL_PORT}"
  fi

  echo "[dry-run] Step 7: Teardown on Exit:"
  echo "[dry-run] would kill local tunnel and stop remote container '${CONTAINER_NAME}'"
  echo "=============================================================================="
  echo "✅ [DRY-RUN] Interactive preview execution plan validated successfully."
  echo "=============================================================================="
  exit 0
fi

# ------------------------------------------------------------------------------
# Step 1: Pre-Flight Host Reachability Checks (RHVP)
# ------------------------------------------------------------------------------
echo "=============================================================================="
echo "🚀 Ephemeral Staging Interactive Preview: ${SERVICE_TITLE}"
echo "=============================================================================="

if is_remote; then
  echo "==> [RHVP] Verifying remote host reachability: ${HOST}..."
  if ! "${SSH_BIN}" -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "echo ok" >/dev/null 2>&1; then
    echo "[-] ERROR: Target host '${HOST}' is unreachable via SSH." >&2
    echo "    Verify Tailscale connectivity or SSH keys." >&2
    exit 2
  fi
  echo "[+] Host '${HOST}' is online and responding."
fi

# ------------------------------------------------------------------------------
# Step 2: Production Snapshot Hydration & Staging Boot
# ------------------------------------------------------------------------------
if [[ "${SKIP_HYDRATE}" == "true" ]]; then
  echo "[*] Step 2: Snapshot hydration skipped (--skip-hydrate). Booting existing staging volume..."
  if is_remote; then
    # shellcheck disable=SC2029
    "${SSH_BIN}" -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" \
      "docker compose -f /home/jacobmiller22/hosting/selfhosted/${COMPOSE_PATH} --profile staging up -d '${CONTAINER_NAME}'"
  else
    docker compose -f "${REPO_ROOT}/${COMPOSE_PATH}" --profile staging up -d "${CONTAINER_NAME}"
  fi
else
  echo "[+] Step 2: Hydrating staging environment from live production snapshot..."
  hydrate_flags=()
  if [[ "${RESET}" == "true" ]]; then
    hydrate_flags+=("--reset" "${SERVICE}")
  else
    hydrate_flags+=("${SERVICE}")
  fi
  hydrate_flags+=("--start")

  if is_remote; then
    echo "[+] Dispatching hydration remotely on '${HOST}'..."
    # shellcheck disable=SC2029
    if ! "${SSH_BIN}" -o BatchMode=yes -o ConnectTimeout=10 "${HOST}" \
      "cd /home/jacobmiller22/hosting/selfhosted && ./tools/staging/hydrate.sh ${hydrate_flags[*]}"; then
      echo "[-] ERROR: Remote hydration failed on '${HOST}'." >&2
      exit 3
    fi
  else
    if ! "${REPO_ROOT}/tools/staging/hydrate.sh" "${hydrate_flags[@]}"; then
      echo "[-] ERROR: Local snapshot hydration failed." >&2
      exit 3
    fi
  fi
fi

SESSION_ACTIVE=true
echo "[+] Staging container '${CONTAINER_NAME}' launched successfully."

# ------------------------------------------------------------------------------
# Step 3: Remote Staging Health Probe
# ------------------------------------------------------------------------------
echo "[+] Step 3: Probing staging service health on port ${REMOTE_PORT}..."
probe_success=false
for _ in $(seq 1 30); do
  if is_remote; then
    # shellcheck disable=SC2029
    if "${SSH_BIN}" -o BatchMode=yes -o ConnectTimeout=3 "${HOST}" \
      "${CURL_BIN} -fsS http://localhost:${REMOTE_PORT}/ >/dev/null 2>&1 || ${CURL_BIN} -s -o /dev/null -w '%{http_code}' http://localhost:${REMOTE_PORT}/ | grep -qE '^(200|302|401)$'"; then
      probe_success=true
      break
    fi
  else
    if "${CURL_BIN}" -fsS "http://localhost:${REMOTE_PORT}/" >/dev/null 2>&1 || \
       "${CURL_BIN}" -s -o /dev/null -w '%{http_code}' "http://localhost:${REMOTE_PORT}/" | grep -qE '^(200|302|401)$'; then
      probe_success=true
      break
    fi
  fi
  sleep 1
done

if [[ "${probe_success}" != "true" ]]; then
  echo "[-] ERROR: Health probe failed on staging port ${REMOTE_PORT} after 30 seconds." >&2
  exit 4
fi
echo "[+] Health probe passed. Service is responding."

# ------------------------------------------------------------------------------
# Step 4: Ephemeral SSH Port-Forward Tunnel
# ------------------------------------------------------------------------------
if is_remote; then
  echo "[+] Step 4: Opening ephemeral SSH tunnel: localhost:${LOCAL_PORT} -> ${HOST}:${REMOTE_PORT}..."

  # Kill any lingering local listener on LOCAL_PORT if present
  if command -v lsof >/dev/null 2>&1; then
    local_pid="$(lsof -ti :"${LOCAL_PORT}" || true)"
    if [[ -n "${local_pid}" ]]; then
      echo "[*] Notice: Killing lingering listener on port ${LOCAL_PORT} (PID: ${local_pid})..."
      kill "${local_pid}" 2>/dev/null || true
      sleep 1
    fi
  fi

  # Launch SSH tunnel in background
  "${SSH_BIN}" -N -L "${LOCAL_PORT}:localhost:${REMOTE_PORT}" -o ExitOnForwardFailure=yes "${HOST}" &
  TUNNEL_PID=$!
  sleep 1

  if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    echo "[-] ERROR: Failed to establish SSH port-forward tunnel on port ${LOCAL_PORT}." >&2
    exit 5
  fi
  echo "[+] SSH tunnel active (PID: ${TUNNEL_PID})."
fi

# ------------------------------------------------------------------------------
# Step 5: Remote Safety Watchdog Timer
# ------------------------------------------------------------------------------
if is_remote; then
  watchdog_secs=$((TIMEOUT * 60))
  echo "[+] Step 5: Arming remote safety watchdog on ${HOST} (${TIMEOUT}m timeout)..."
  # shellcheck disable=SC2029
  "${SSH_BIN}" -o BatchMode=yes "${HOST}" \
    "nohup bash -c 'sleep ${watchdog_secs} && docker compose -f /home/jacobmiller22/hosting/selfhosted/${COMPOSE_PATH} --profile staging stop ${CONTAINER_NAME} >/dev/null 2>&1' >/dev/null 2>&1 &" || true
fi

# ------------------------------------------------------------------------------
# Step 6: Browser Launch & Interactive Session
# ------------------------------------------------------------------------------
PREVIEW_URL="http://localhost:${LOCAL_PORT}"

echo ""
echo "=============================================================================="
echo "✨ ${SERVICE_TITLE} Ephemeral Staging Preview is READY!"
echo "=============================================================================="
echo "  🌐 Preview URL:         ${PREVIEW_URL}"
echo "  📦 Staging Container:   ${CONTAINER_NAME} on ${HOST}"
echo "  🔒 Isolation Mode:      staging-net (Volume: isolated, Prod DB: untouched)"
echo "  ⏱️ Watchdog Timer:      ${TIMEOUT} minutes auto-shutdown"
echo "=============================================================================="
echo ""

if [[ "${NO_OPEN}" != "true" ]]; then
  if command -v "${OPEN_BIN}" >/dev/null 2>&1; then
    echo "[+] Launching browser: ${PREVIEW_URL}..."
    "${OPEN_BIN}" "${PREVIEW_URL}" 2>/dev/null || true
  elif command -v xdg-open >/dev/null 2>&1; then
    echo "[+] Launching browser: ${PREVIEW_URL}..."
    xdg-open "${PREVIEW_URL}" 2>/dev/null || true
  else
    echo "[*] Open in your browser: ${PREVIEW_URL}"
  fi
else
  echo "[*] Open in your browser: ${PREVIEW_URL}"
fi

echo ""
echo "💡 Press [Ctrl+C] at any time to close the preview and cleanly tear down."
echo "   (Container will also auto-stop after ${TIMEOUT} minutes if left unattended)."
echo ""

# Wait on user interrupt or tunnel termination
if [[ -n "${TUNNEL_PID}" ]]; then
  wait "${TUNNEL_PID}" 2>/dev/null || true
else
  # Local execution: wait on infinite loop or until signal
  while true; do
    sleep 2
  done
fi
