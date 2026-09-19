#!/usr/bin/env bash
# ==============================================================================
# Disaster Recovery (DR): Ephemeral Staging Container Smoke Test Runner
# ==============================================================================
# Orchestrates zero-blast-radius failover testing:
# 1. Verifies host reachability via SSH (Remote Host Verification Protocol) or local.
# 2. Prepares isolated Docker network ('staging-net') preventing traffic leaks.
# 3. Spins up ephemeral staging containers on isolated, non-conflicting ports:
#    - Actual Budget: port 5006:5006 (assert HTTP 200 or 302 within timeout)
#    - Vaultwarden:   port 7278:80   (assert HTTP 200 within timeout)
# 4. Enforces resource constraints (256m memory, 0.50 CPU).
# 5. Guaranteed teardown and ephemeral cleanup on EXIT/ERR/INT/TERM via traps
#    (unless --keep is explicitly provided).
# 6. Complete --dry-run mode for deterministic execution in CI/CD and workstation tests.
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Defaults & Initialization
# ------------------------------------------------------------------------------
SERVICE="all"
DATA_DIR=""
TIMEOUT=30
KEEP=false
DRY_RUN=false
HOST=""

DOCKER_BIN="${DOCKER_CMD:-docker}"
CURL_BIN="${CURL_CMD:-curl}"
SSH_BIN="${SSH_CMD:-ssh}"

# State tracking for teardown traps
declare -a LAUNCHED_CONTAINERS=()
CREATED_STAGING_NET=false
CLEANED_UP=false

# ------------------------------------------------------------------------------
# Help & Usage Display
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Orchestrates ephemeral staging container spin-up, endpoint smoke testing, and teardown.

Services:
  actual                     Actual Budget (port 5006, health probe /)
  vaultwarden                Vaultwarden   (port 7278, health probe /alive)
  all                        Run smoke tests for all supported services (default)

Options:
  -s, --service <name>       Service to test (actual, vaultwarden, or all; default: all)
  -d, --data-dir <path>      Directory containing decrypted test database files
  -t, --timeout <sec>        Timeout in seconds waiting for service to respond (default: 30)
  -k, --keep                 Skip automatic teardown and retain containers for debugging
      --dry-run              Print planned commands without modifying Docker states
      --host <hostname>      Remote host for execution via SSH (default: local/direct or bjorn)
  -h, --help                 Display this help message and exit

Exit Codes:
  0   All staging smoke tests passed successfully
  1   CLI syntax, option parsing, or argument validation error
  2   Remote host unreachable via SSH (Remote Host Verification Protocol)
  3   Staging network or container spin-up failure
  4   Service health probe failure or timeout exceeded
EOF
}

# ------------------------------------------------------------------------------
# Parse CLI Arguments
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
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
    -d|--data-dir)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      DATA_DIR="$2"
      shift 2
      ;;
    --data-dir=*)
      DATA_DIR="${1#*=}"
      shift
      ;;
    -t|--timeout)
      if [[ -z "${2:-}" || ( "${2}" == -* && ! "${2}" =~ ^-[0-9]+$ ) ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      TIMEOUT="$2"
      shift 2
      ;;
    --timeout=*)
      TIMEOUT="${1#*=}"
      shift
      ;;
    -k|--keep)
      KEEP=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --host)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      HOST="$2"
      shift 2
      ;;
    --host=*)
      HOST="${1#*=}"
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
# Input Validation
# ------------------------------------------------------------------------------
case "${SERVICE}" in
  actual|vaultwarden|all)
    ;;
  *)
    echo "[-] ERROR: Unsupported service '${SERVICE}'. Supported services: actual, vaultwarden, all." >&2
    exit 1
    ;;
esac

if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT}" -le 0 ]]; then
  echo "[-] ERROR: Timeout must be a positive integer (got '${TIMEOUT}')." >&2
  exit 1
fi

if [[ -n "${DATA_DIR}" ]]; then
  if [[ ! -d "${DATA_DIR}" ]]; then
    echo "[-] ERROR: Specified data directory does not exist: ${DATA_DIR}" >&2
    exit 1
  fi
fi

# ------------------------------------------------------------------------------
# Teardown & Isolation Guarantee Trap
# ------------------------------------------------------------------------------
# shellcheck disable=SC2329
cleanup() {
  local exit_code=$?
  trap - ERR EXIT INT TERM

  if [[ "${DRY_RUN}" == "true" || "${CLEANED_UP}" == "true" ]]; then
    return "${exit_code}"
  fi
  CLEANED_UP=true

  if [[ "${KEEP}" == "true" ]]; then
    echo "[*] Retention enabled (--keep): staging containers and networks retained for debugging."
    return "${exit_code}"
  fi

  echo "[*] Executing guaranteed teardown trap: stopping and cleaning up ephemeral staging resources..."
  for container in "${LAUNCHED_CONTAINERS[@]}"; do
    echo "    Stopping and removing staging container: ${container}..."
    if [[ -n "${HOST}" && "${HOST}" != "local" && "${HOST}" != "localhost" ]]; then
      # shellcheck disable=SC2029
      "${SSH_BIN}" "${HOST}" "${DOCKER_BIN} stop ${container} >/dev/null 2>&1 || true; ${DOCKER_BIN} rm -f ${container} >/dev/null 2>&1 || true" || true
    else
      "${DOCKER_BIN}" stop "${container}" >/dev/null 2>&1 || true
      "${DOCKER_BIN}" rm -f "${container}" >/dev/null 2>&1 || true
    fi
  done

  if [[ "${CREATED_STAGING_NET}" == "true" ]]; then
    echo "    Removing ephemeral network: staging-net..."
    if [[ -n "${HOST}" && "${HOST}" != "local" && "${HOST}" != "localhost" ]]; then
      # shellcheck disable=SC2029
      "${SSH_BIN}" "${HOST}" "${DOCKER_BIN} network rm staging-net >/dev/null 2>&1 || true" || true
    else
      "${DOCKER_BIN}" network rm staging-net >/dev/null 2>&1 || true
    fi
  fi

  return "${exit_code}"
}
trap cleanup ERR EXIT INT TERM

# ------------------------------------------------------------------------------
# Remote Host Reachability (RHVP)
# ------------------------------------------------------------------------------
is_remote() {
  [[ -n "${HOST}" && "${HOST}" != "local" && "${HOST}" != "localhost" ]]
}

if is_remote; then
  if [[ "${DRY_RUN}" != "true" ]]; then
    echo "==> [RHVP] Verifying remote host reachability: ${HOST}..."
    if ! "${SSH_BIN}" -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "echo ok" >/dev/null 2>&1; then
      echo "[-] ERROR: Remote host '${HOST}' is unreachable via SSH." >&2
      exit 2
    fi
    echo "    Remote host '${HOST}' is reachable."
  fi
fi

# ------------------------------------------------------------------------------
# Target Services Definition
# ------------------------------------------------------------------------------
declare -a TARGET_SERVICES=()
case "${SERVICE}" in
  actual)
    TARGET_SERVICES=("actual")
    ;;
  vaultwarden)
    TARGET_SERVICES=("vaultwarden")
    ;;
  all)
    TARGET_SERVICES=("actual" "vaultwarden")
    ;;
esac

# ------------------------------------------------------------------------------
# Dry-Run Execution Plan Display
# ------------------------------------------------------------------------------
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "=============================================================================="
  echo "🚀 [DRY-RUN] Ephemeral Staging Smoke Test Runner"
  echo "=============================================================================="
  if is_remote; then
    echo "[dry-run] Pre-flight: ${SSH_BIN} -o BatchMode=yes -o ConnectTimeout=5 ${HOST} 'echo ok'"
  fi

  prefix=""
  if is_remote; then
    prefix="${SSH_BIN} ${HOST} "
  fi

  echo "[dry-run] Network: ${prefix}${DOCKER_BIN} network inspect staging-net >/dev/null 2>&1 || ${prefix}${DOCKER_BIN} network create staging-net"

  for svc in "${TARGET_SERVICES[@]}"; do
    case "${svc}" in
      actual)
        c_name="actual-server-staging"
        port_flag="-p 5006:5006"
        image="docker.io/actualbudget/actual-server:26.9.0"
        vol_src="actual-stage-data"
        if [[ -n "${DATA_DIR}" ]]; then
          if [[ -d "${DATA_DIR}/actual" ]]; then
            vol_src="${DATA_DIR}/actual"
          else
            vol_src="${DATA_DIR}"
          fi
        fi
        probe_url="http://localhost:5006/"
        expected_codes="200|302"
        extra_flags=""
        ;;
      vaultwarden)
        c_name="vaultwarden-staging"
        port_flag="-p 7278:80"
        image="vaultwarden/server:1.35.4"
        vol_src="vw-stage-data"
        if [[ -n "${DATA_DIR}" ]]; then
          if [[ -d "${DATA_DIR}/vaultwarden" ]]; then
            vol_src="${DATA_DIR}/vaultwarden"
          else
            vol_src="${DATA_DIR}"
          fi
        fi
        probe_url="http://localhost:7278/alive"
        expected_codes="200"
        extra_flags="-e DOMAIN=http://localhost:7278 -e SIGNUPS_ALLOWED=false"
        ;;
    esac

    echo ""
    echo "[dry-run] Service: ${svc}"
    echo "[dry-run] Pre-cleanup: ${prefix}${DOCKER_BIN} stop ${c_name} 2>/dev/null || true; ${prefix}${DOCKER_BIN} rm -f ${c_name} 2>/dev/null || true"
    echo "[dry-run] Spin-up: ${prefix}${DOCKER_BIN} run -d --name ${c_name} --network staging-net ${port_flag} --memory 256m --cpus 0.50 ${extra_flags} -v ${vol_src}:/data ${image}"
    echo "[dry-run] Health Probe: ${prefix}${CURL_BIN} -fsS ${probe_url} (assert HTTP ${expected_codes} within ${TIMEOUT}s)"
    echo "[dry-run] Log Inspection: ${prefix}${DOCKER_BIN} logs --tail 50 ${c_name}"

    if [[ "${KEEP}" == "true" ]]; then
      echo "[dry-run] Teardown: Skipped (--keep enabled; container ${c_name} retained)"
    else
      echo "[dry-run] Teardown: ${prefix}${DOCKER_BIN} stop ${c_name} && ${prefix}${DOCKER_BIN} rm -f ${c_name}"
    fi
  done

  if [[ "${KEEP}" == "false" ]]; then
    echo ""
    echo "[dry-run] Network Teardown: ${prefix}${DOCKER_BIN} network rm staging-net"
  fi

  echo "=============================================================================="
  echo "✅ [DRY-RUN] Ephemeral staging smoke test plan validated successfully."
  echo "=============================================================================="
  exit 0
fi

# ------------------------------------------------------------------------------
# Helper Execution Wrappers
# ------------------------------------------------------------------------------
run_remote_or_local() {
  local cmd="$1"
  if is_remote; then
    # shellcheck disable=SC2029
    "${SSH_BIN}" "${HOST}" "${cmd}"
  else
    bash -c "${cmd}"
  fi
}

run_curl_probe() {
  local url="$1"
  if is_remote; then
    # shellcheck disable=SC2029
    "${SSH_BIN}" "${HOST}" "${CURL_BIN} -s -o /dev/null -w '%{http_code}' '${url}'" 2>/dev/null || echo "000"
  else
    "${CURL_BIN}" -s -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null || echo "000"
  fi
}

# ------------------------------------------------------------------------------
# Step 1: Ensure Isolated Staging Network
# ------------------------------------------------------------------------------
echo "==> Ensuring isolated Docker network 'staging-net' exists..."
if ! run_remote_or_local "${DOCKER_BIN} network inspect staging-net >/dev/null 2>&1"; then
  echo "    Creating isolated bridge network 'staging-net'..."
  if ! run_remote_or_local "${DOCKER_BIN} network create staging-net >/dev/null 2>&1"; then
    echo "[-] ERROR: Failed to create isolated Docker network 'staging-net'." >&2
    exit 3
  fi
  CREATED_STAGING_NET=true
fi
echo "    Isolated network 'staging-net' is ready."

# ------------------------------------------------------------------------------
# Step 2: Spin Up and Smoke Test Each Service
# ------------------------------------------------------------------------------
for svc in "${TARGET_SERVICES[@]}"; do
  echo ""
  echo "=============================================================================="
  echo "🧪 Running Ephemeral Staging Smoke Test: ${svc}"
  echo "=============================================================================="

  case "${svc}" in
    actual)
      CONTAINER_NAME="actual-server-staging"
      IMAGE="docker.io/actualbudget/actual-server:26.9.0"
      PORT_MAP="5006:5006"
      PROBE_URL="http://localhost:5006/"
      EXPECTED_CODE_REGEX="^(200|302)$"
      VOL_SRC="actual-stage-data"
      if [[ -n "${DATA_DIR}" ]]; then
        if [[ -d "${DATA_DIR}/actual" ]]; then
          VOL_SRC="${DATA_DIR}/actual"
        else
          VOL_SRC="${DATA_DIR}"
        fi
      fi
      EXTRA_ENV=""
      ;;
    vaultwarden)
      CONTAINER_NAME="vaultwarden-staging"
      IMAGE="vaultwarden/server:1.35.4"
      PORT_MAP="7278:80"
      PROBE_URL="http://localhost:7278/alive"
      EXPECTED_CODE_REGEX="^200$"
      VOL_SRC="vw-stage-data"
      if [[ -n "${DATA_DIR}" ]]; then
        if [[ -d "${DATA_DIR}/vaultwarden" ]]; then
          VOL_SRC="${DATA_DIR}/vaultwarden"
        else
          VOL_SRC="${DATA_DIR}"
        fi
      fi
      EXTRA_ENV="-e DOMAIN=http://localhost:7278 -e SIGNUPS_ALLOWED=false"
      ;;
  esac

  # 1. Clean up any pre-existing container with same name
  echo "--> Stopping any existing staging container '${CONTAINER_NAME}'..."
  run_remote_or_local "${DOCKER_BIN} stop ${CONTAINER_NAME} >/dev/null 2>&1 || true"
  run_remote_or_local "${DOCKER_BIN} rm -f ${CONTAINER_NAME} >/dev/null 2>&1 || true"

  # 2. Launch ephemeral container
  echo "--> Launching ephemeral container '${CONTAINER_NAME}' on port ${PORT_MAP}..."
  DOCKER_RUN_CMD="${DOCKER_BIN} run -d --name ${CONTAINER_NAME} --network staging-net -p ${PORT_MAP} --memory 256m --cpus 0.50 ${EXTRA_ENV} -v ${VOL_SRC}:/data ${IMAGE}"
  if ! run_remote_or_local "${DOCKER_RUN_CMD} >/dev/null 2>&1"; then
    echo "[-] ERROR: Failed to launch staging container '${CONTAINER_NAME}'." >&2
    exit 3
  fi
  LAUNCHED_CONTAINERS+=("${CONTAINER_NAME}")

  # 3. HTTP Health Probing Loop
  echo "--> Probing health endpoint '${PROBE_URL}' (timeout: ${TIMEOUT}s)..."
  start_time=$(date +%s)
  probe_success=false
  last_code="000"

  while true; do
    http_code=$(run_curl_probe "${PROBE_URL}")
    last_code="${http_code}"

    if [[ "${http_code}" =~ ${EXPECTED_CODE_REGEX} ]]; then
      now=$(date +%s)
      elapsed=$((now - start_time))
      echo "[+] Success: ${svc} endpoint responded with HTTP ${http_code} within ${elapsed}s."
      probe_success=true
      break
    fi

    # Check container status
    c_status=$(run_remote_or_local "${DOCKER_BIN} inspect --format '{{.State.Status}}' ${CONTAINER_NAME} 2>/dev/null" || echo "unknown")
    if [[ "${c_status}" != "running" ]]; then
      echo "[-] ERROR: Staging container '${CONTAINER_NAME}' stopped unexpectedly with status '${c_status}'." >&2
      echo "--- Container Logs (tail 50) ---" >&2
      run_remote_or_local "${DOCKER_BIN} logs --tail 50 ${CONTAINER_NAME}" >&2 || true
      exit 4
    fi

    now=$(date +%s)
    elapsed=$((now - start_time))
    if [[ ${elapsed} -ge ${TIMEOUT} ]]; then
      break
    fi

    sleep 1
  done

  if [[ "${probe_success}" != "true" ]]; then
    echo "[-] ERROR: Timed out waiting for ${svc} endpoint '${PROBE_URL}' (last response HTTP ${last_code})." >&2
    echo "--- Container Logs (tail 50) ---" >&2
    run_remote_or_local "${DOCKER_BIN} logs --tail 50 ${CONTAINER_NAME}" >&2 || true
    exit 4
  fi

  # 4. Check for critical error signatures in logs
  echo "--> Inspecting container logs for fatal exceptions or lock panics..."
  log_output=$(run_remote_or_local "${DOCKER_BIN} logs --tail 100 ${CONTAINER_NAME} 2>&1" || true)
  if echo "${log_output}" | grep -Ei "panic:|fatal error:|database is locked" >/dev/null 2>&1; then
    echo "[-] ERROR: Fatal error detected in ${CONTAINER_NAME} logs:" >&2
    echo "${log_output}" | grep -Ei "panic:|fatal error:|database is locked" >&2
    exit 4
  fi
  echo "    No fatal panic or lock errors detected in container logs."
done

# ------------------------------------------------------------------------------
# Summary & Completion
# ------------------------------------------------------------------------------
echo ""
echo "=============================================================================="
echo "✅ Disaster Recovery Staging Smoke Test PASSED: All services verified."
echo "=============================================================================="

exit 0
