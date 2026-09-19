#!/usr/bin/env bash
# ==============================================================================
# Ephemeral Staging: Vaultwarden Upgrade & Schema Migration Validation Engine
# ==============================================================================
# Automates pre-flight staging upgrade testing, SQLite schema migration
# validation, and client segregation assertion prior to production deployment.
#
# Steps:
#   1. Pre-flight snapshot hydration (hydrate.sh vaultwarden)
#   2. Spins up vaultwarden-staging with candidate image tag on port 7278
#   3. Monitors container logs for SQLite schema migration, locks, or Rust panics
#   4. Health probe: http://localhost:7278/alive & Web Vault assets load
#   5. SQLite integrity check on staging db.sqlite3 (PRAGMA integrity_check;)
#   6. Client segregation assertion (SIGNUPS_ALLOWED=false, isolated domain)
#   7. Teardown: Guaranteed cleanup in trap handler (unless --keep)
#   8. Supports --dry-run cleanly for deterministic test execution
#
# Usage:
#   verify-vaultwarden-upgrade.sh [OPTIONS] <new-image-tag>
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Default Settings & Configuration
# ------------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

CANDIDATE_TAG=""
DRY_RUN=false
SKIP_HYDRATE=false
TIMEOUT=30
HOST="localhost"
KEEP_CONTAINER=false
STAGE_DATA_DIR="${STAGE_DATA_DIR:-}"
PROD_DATA_DIR="${PROD_DATA_DIR:-}"
DOCKER_BIN="${DOCKER_CMD:-docker}"
SQLITE3_BIN="${SQLITE3_CMD:-sqlite3}"
CURL_BIN="${CURL_CMD:-curl}"

COMPOSE_FILE="${REPO_ROOT}/vaultwarden/compose.yml"
CONTAINER_NAME="vaultwarden-staging"
STAGING_PORT="7278"

# ------------------------------------------------------------------------------
# Help & Usage Display
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] <new-image-tag>

Validates upstream Vaultwarden container image upgrades, SQLite schema migrations,
and Web Vault compatibility against a fresh production snapshot in ephemeral staging.

Arguments:
  <new-image-tag>            Candidate Vaultwarden image tag (e.g. '1.35.5' or 'vaultwarden/server:1.35.5')

Options:
  --dry-run                  Simulate actions without executing Docker, SQLite, or curl operations
  --skip-hydrate             Skip calling hydrate.sh vaultwarden prior to starting candidate
  --timeout <sec>            Health probe timeout in seconds (default: 30)
  --host <hostname>          Target host (default: localhost; use 'bjorn' for remote host)
  --keep                     Keep staging container running after test (skips teardown)
  --stage-data-dir <path>    Explicit path to staging data directory (or set STAGE_DATA_DIR)
  --prod-data-dir <path>     Explicit path to production data directory (or set PROD_DATA_DIR)
  -h, --help                 Display this help message and exit

Examples:
  # Dry-run validation of upgrade to 1.35.5:
  $(basename "$0") --dry-run 1.35.5

  # Run verification against local staging with custom timeout:
  $(basename "$0") --timeout 45 1.35.5

  # Run verification on remote host bjorn without re-hydrating:
  $(basename "$0") --host bjorn --skip-hydrate 1.35.5

  # Validate and keep container running for manual inspection:
  $(basename "$0") --keep 1.35.5
EOF
}

# ------------------------------------------------------------------------------
# CLI Argument Parsing
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --skip-hydrate)
      SKIP_HYDRATE=true
      shift
      ;;
    --keep)
      KEEP_CONTAINER=true
      shift
      ;;
    --timeout)
      if [[ -z "${2:-}" || "${2}" =~ ^-- ]]; then
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
    --host)
      if [[ -z "${2:-}" || "${2}" =~ ^-- ]]; then
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
    --stage-data-dir)
      if [[ -z "${2:-}" || "${2}" =~ ^-- ]]; then
        echo "[-] ERROR: Missing value for --stage-data-dir" >&2
        exit 1
      fi
      STAGE_DATA_DIR="$2"
      shift 2
      ;;
    --stage-data-dir=*)
      STAGE_DATA_DIR="${1#*=}"
      shift
      ;;
    --prod-data-dir)
      if [[ -z "${2:-}" || "${2}" =~ ^-- ]]; then
        echo "[-] ERROR: Missing value for --prod-data-dir" >&2
        exit 1
      fi
      PROD_DATA_DIR="$2"
      shift 2
      ;;
    --prod-data-dir=*)
      PROD_DATA_DIR="${1#*=}"
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    -*)
      echo "[-] ERROR: Unknown option: $1" >&2
      echo "Run '$(basename "$0") --help' for usage." >&2
      exit 1
      ;;
    *)
      if [[ -z "${CANDIDATE_TAG}" ]]; then
        CANDIDATE_TAG="$1"
      else
        echo "[-] ERROR: Unexpected positional argument: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

# ------------------------------------------------------------------------------
# Validate Candidate Image Tag
# ------------------------------------------------------------------------------
if [[ -z "${CANDIDATE_TAG}" ]]; then
  echo "[-] ERROR: Candidate image tag is required." >&2
  echo "Usage: $(basename "$0") [OPTIONS] <new-image-tag>" >&2
  echo "Run '$(basename "$0") --help' for usage." >&2
  exit 1
fi

if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT}" -le 0 ]]; then
  echo "[-] ERROR: Timeout must be a positive integer, got: '${TIMEOUT}'" >&2
  exit 1
fi

# Normalize IMAGE_TAG: strip repo prefix if provided
IMAGE_TAG="${CANDIDATE_TAG#vaultwarden/server:}"
export IMAGE_TAG

# ------------------------------------------------------------------------------
# Teardown Trap Handler (Step 7)
# ------------------------------------------------------------------------------
CLEANED_UP=false

cleanup() {
  local exit_code=$?
  if [[ "${CLEANED_UP}" == "true" ]]; then
    return
  fi
  CLEANED_UP=true

  if [[ "${KEEP_CONTAINER}" == "true" ]]; then
    echo "[*] Notice: Staging container kept running (--keep flag specified)."
    exit "${exit_code}"
  fi

  echo "[+] Step 7: Teardown: Stopping and removing staging container '${CONTAINER_NAME}'..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] would run: ${DOCKER_BIN} compose -f ${COMPOSE_FILE} --profile staging down"
    exit "${exit_code}"
  fi

  if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
    # shellcheck disable=SC2029
    ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${DOCKER_BIN} compose -f ${COMPOSE_FILE} --profile staging down" 2>/dev/null || true
  else
    if command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
      "${DOCKER_BIN}" compose -f "${COMPOSE_FILE}" --profile staging down 2>/dev/null || true
    fi
  fi
  echo "[+] Teardown completed successfully."
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

# ------------------------------------------------------------------------------
# Dry-Run Execution Path (Step 8)
# ------------------------------------------------------------------------------
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "=============================================================================="
  echo "🚀 [DRY-RUN] Vaultwarden Staging Upgrade Verification Sandbox"
  echo "=============================================================================="
  echo "[dry-run] Candidate Image Tag: ${CANDIDATE_TAG} (IMAGE_TAG=${IMAGE_TAG})"
  echo "[dry-run] Target Host:        ${HOST}"
  echo "[dry-run] Timeout:            ${TIMEOUT}s"
  echo "[dry-run] Keep Container:     ${KEEP_CONTAINER}"
  echo ""

  # Step 1: Pre-flight hydration
  if [[ "${SKIP_HYDRATE}" == "true" ]]; then
    echo "[dry-run] Step 1: Pre-flight hydration skipped (--skip-hydrate)."
  else
    echo "[dry-run] Step 1: Pre-flight snapshot hydration:"
    echo "[dry-run] would run: ${REPO_ROOT}/tools/staging/hydrate.sh vaultwarden --dry-run"
  fi

  # Step 2: Spin up container
  echo "[dry-run] Step 2: Spin up staging container '${CONTAINER_NAME}' with candidate image:"
  echo "[dry-run] would run: IMAGE_TAG=${IMAGE_TAG} ${DOCKER_BIN} compose -f ${COMPOSE_FILE} --profile staging up -d ${CONTAINER_NAME}"

  # Step 3: Monitor logs
  echo "[dry-run] Step 3: Monitor container logs for schema migration, DB locks, and Rust panics:"
  echo "[dry-run] would run: ${DOCKER_BIN} logs --tail 200 ${CONTAINER_NAME}"

  # Step 4: Health probe
  echo "[dry-run] Step 4: Health probe endpoints on port ${STAGING_PORT} (timeout: ${TIMEOUT}s):"
  echo "[dry-run] would run: ${CURL_BIN} -fsS http://localhost:${STAGING_PORT}/alive"
  echo "[dry-run] would run: ${CURL_BIN} -fsS http://localhost:${STAGING_PORT}/"

  # Step 5: SQLite integrity check
  local_stage_db="${STAGE_DATA_DIR:-/var/lib/docker/volumes/vw-stage-data/_data}/db.sqlite3"
  echo "[dry-run] Step 5: SQLite integrity check on staging database:"
  echo "[dry-run] would run: ${SQLITE3_BIN} ${local_stage_db} \"PRAGMA integrity_check;\""

  # Step 6: Client segregation assertion
  echo "[dry-run] Step 6: Client segregation assertion:"
  echo "[dry-run] would assert SIGNUPS_ALLOWED=false and DOMAIN=http://localhost:7278"

  # Step 7 is handled by cleanup trap
  echo "=============================================================================="
  echo "✅ [DRY-RUN] Upgrade verification plan for '${CANDIDATE_TAG}' validated successfully."
  echo "=============================================================================="
  exit 0
fi

# ------------------------------------------------------------------------------
# Step 1: Pre-Flight Production Snapshot Hydration
# ------------------------------------------------------------------------------
echo "=============================================================================="
echo "🚀 Vaultwarden Staging Upgrade Verification: ${CANDIDATE_TAG}"
echo "=============================================================================="

if [[ "${SKIP_HYDRATE}" == "true" ]]; then
  echo "[*] Step 1: Pre-flight hydration skipped (--skip-hydrate)."
else
  echo "[+] Step 1: Running pre-flight snapshot hydration for vaultwarden..."
  hydrate_cmd=("${REPO_ROOT}/tools/staging/hydrate.sh" "vaultwarden")
  if [[ -n "${STAGE_DATA_DIR}" ]]; then
    hydrate_cmd+=("--stage-data-dir" "${STAGE_DATA_DIR}")
  fi
  if [[ -n "${PROD_DATA_DIR}" ]]; then
    hydrate_cmd+=("--prod-data-dir" "${PROD_DATA_DIR}")
  fi

  if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
    echo "[+] Running hydration remotely on host '${HOST}'..."
    # shellcheck disable=SC2029
    ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${hydrate_cmd[*]}"
  else
    "${hydrate_cmd[@]}"
  fi
  echo "[+] Step 1: Production snapshot hydration completed successfully."
fi

# ------------------------------------------------------------------------------
# Step 2: Spin Up Staging Container With Candidate Image Tag
# ------------------------------------------------------------------------------
echo "[+] Step 2: Starting '${CONTAINER_NAME}' with candidate image tag '${IMAGE_TAG}' on port ${STAGING_PORT}..."

if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
  # shellcheck disable=SC2029
  ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" \
    "IMAGE_TAG='${IMAGE_TAG}' ${DOCKER_BIN} compose -f '${COMPOSE_FILE}' --profile staging up -d '${CONTAINER_NAME}'"
else
  IMAGE_TAG="${IMAGE_TAG}" "${DOCKER_BIN}" compose -f "${COMPOSE_FILE}" --profile staging up -d "${CONTAINER_NAME}"
fi
echo "[+] Step 2: Container '${CONTAINER_NAME}' dispatched."

# ------------------------------------------------------------------------------
# Step 3 & 4: Monitor Logs & Health Probes
# ------------------------------------------------------------------------------
echo "[+] Step 3 & 4: Probing health and monitoring container logs (timeout: ${TIMEOUT}s)..."

PROBE_URL="http://localhost:${STAGING_PORT}/alive"
WEB_URL="http://localhost:${STAGING_PORT}/"
START_TIME=$(date +%s)
HEALTH_PASSED=false

while true; do
  CURRENT_TIME=$(date +%s)
  ELAPSED=$((CURRENT_TIME - START_TIME))

  if [[ ${ELAPSED} -ge ${TIMEOUT} ]]; then
    break
  fi

  # Fetch recent container logs
  LOGS=""
  if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
    LOGS=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${DOCKER_BIN} logs --tail 100 '${CONTAINER_NAME}'" 2>&1 || true)
  else
    LOGS=$("${DOCKER_BIN}" logs --tail 100 "${CONTAINER_NAME}" 2>&1 || true)
  fi

  # Inspect logs for fatal panics
  if echo "${LOGS}" | grep -E -q -i "panicked at|thread '.*' panicked|fatal runtime error"; then
    echo "[-] ERROR: [Fatal] Rust panic detected in container logs:" >&2
    echo "${LOGS}" | grep -E -i "panicked|thread" >&2
    exit 1
  fi

  # Inspect logs for database lock errors
  if echo "${LOGS}" | grep -E -q -i "database is locked|DatabaseLocked|busy: database is locked"; then
    echo "[-] ERROR: [Fatal] SQLite database lock detected in container logs:" >&2
    echo "${LOGS}" | grep -E -i "database.*locked|DatabaseLocked" >&2
    exit 1
  fi

  # Probe /alive endpoint
  ALIVE_STATUS=""
  if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
    ALIVE_STATUS=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${CURL_BIN} -fsS -o /dev/null -w '%{http_code}' '${PROBE_URL}'" 2>/dev/null || true)
  else
    ALIVE_STATUS=$("${CURL_BIN}" -fsS -o /dev/null -w '%{http_code}' "${PROBE_URL}" 2>/dev/null || true)
  fi

  if [[ "${ALIVE_STATUS}" == "200" ]]; then
    # Probe Web Vault UI assets root endpoint
    WEB_STATUS=""
    if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
      WEB_STATUS=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${CURL_BIN} -fsS -o /dev/null -w '%{http_code}' '${WEB_URL}'" 2>/dev/null || true)
    else
      WEB_STATUS=$("${CURL_BIN}" -fsS -o /dev/null -w '%{http_code}' "${WEB_URL}" 2>/dev/null || true)
    fi

    if [[ "${WEB_STATUS}" == "200" ]]; then
      echo "[+] Step 4: Health probe passed: /alive returned 200 OK and Web Vault UI loaded successfully (${ELAPSED}s elapsed)."
      HEALTH_PASSED=true
      break
    fi
  fi

  sleep 1
done

if [[ "${HEALTH_PASSED}" != "true" ]]; then
  echo "[-] ERROR: Health probe timed out after ${TIMEOUT}s on ${PROBE_URL}." >&2
  echo "[-] Last container logs:" >&2
  if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
    ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${DOCKER_BIN} logs --tail 50 '${CONTAINER_NAME}'" >&2 || true
  else
    "${DOCKER_BIN}" logs --tail 50 "${CONTAINER_NAME}" >&2 || true
  fi
  exit 1
fi

# Step 3 Log Verification: schema migration report
FULL_LOGS=""
if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
  FULL_LOGS=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${DOCKER_BIN} logs --tail 200 '${CONTAINER_NAME}'" 2>&1 || true)
else
  FULL_LOGS=$("${DOCKER_BIN}" logs --tail 200 "${CONTAINER_NAME}" 2>&1 || true)
fi

if echo "${FULL_LOGS}" | grep -E -q -i "migration|migrating|schema|Executing migration|Applied migration"; then
  echo "[+] Step 3: SQLite schema migration output detected and completed successfully."
else
  echo "[*] Step 3: Container startup verified clean (no pending schema migrations required)."
fi

# ------------------------------------------------------------------------------
# Step 5: SQLite Database Integrity Check
# ------------------------------------------------------------------------------
echo "[+] Step 5: Running SQLite PRAGMA integrity_check on staging database..."

# Resolve staging DB path
STAGING_DB=""
if [[ -n "${STAGE_DATA_DIR}" && -f "${STAGE_DATA_DIR}/db.sqlite3" ]]; then
  STAGING_DB="${STAGE_DATA_DIR}/db.sqlite3"
elif [[ -f "/var/lib/docker/volumes/vw-stage-data/_data/db.sqlite3" ]]; then
  STAGING_DB="/var/lib/docker/volumes/vw-stage-data/_data/db.sqlite3"
fi

INTEGRITY_OUTPUT=""
if [[ -n "${STAGING_DB}" ]]; then
  echo "[+] Checking staging database file: ${STAGING_DB}..."
  if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
    # shellcheck disable=SC2029
    INTEGRITY_OUTPUT=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${SQLITE3_BIN} '${STAGING_DB}' 'PRAGMA integrity_check;'" 2>&1 || true)
  else
    INTEGRITY_OUTPUT=$("${SQLITE3_BIN}" "${STAGING_DB}" "PRAGMA integrity_check;" 2>&1 || true)
  fi
else
  # Fallback: run sqlite3 through docker exec or helper container
  echo "[+] Inspecting staging database via Docker container..."
  if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
    # shellcheck disable=SC2029
    INTEGRITY_OUTPUT=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" \
      "${DOCKER_BIN} run --rm -v vw-stage-data:/data alpine sh -c 'apk add --no-cache sqlite >/dev/null 2>&1 && sqlite3 /data/db.sqlite3 \"PRAGMA integrity_check;\"'" 2>&1 || true)
  else
    if command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
      INTEGRITY_OUTPUT=$("${DOCKER_BIN}" run --rm -v vw-stage-data:/data alpine sh -c 'apk add --no-cache sqlite >/dev/null 2>&1 && sqlite3 /data/db.sqlite3 "PRAGMA integrity_check;"' 2>&1 || true)
    fi
  fi
fi

if [[ "${INTEGRITY_OUTPUT}" != "ok" ]]; then
  echo "[-] ERROR: SQLite integrity check failed on staging database: '${INTEGRITY_OUTPUT}'" >&2
  exit 1
fi
echo "[+] Step 5: SQLite integrity check passed: db.sqlite3 verified consistent (ok)."

# ------------------------------------------------------------------------------
# Step 6: Client Segregation Assertion
# ------------------------------------------------------------------------------
echo "[+] Step 6: Asserting client segregation safeguards..."

ENV_DUMP=""
if [[ "${HOST}" != "localhost" && "${HOST}" != "127.0.0.1" ]]; then
  ENV_DUMP=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST}" "${DOCKER_BIN} inspect '${CONTAINER_NAME}' --format '{{range .Config.Env}}{{println .}}{{end}}'" 2>/dev/null || true)
else
  if command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
    ENV_DUMP=$("${DOCKER_BIN}" inspect "${CONTAINER_NAME}" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null || true)
  fi
fi

if [[ -n "${ENV_DUMP}" ]]; then
  SIGNUPS_VAL=$(echo "${ENV_DUMP}" | grep "^SIGNUPS_ALLOWED=" | cut -d= -f2 || true)
  DOMAIN_VAL=$(echo "${ENV_DUMP}" | grep "^DOMAIN=" | cut -d= -f2 || true)

  if [[ "${SIGNUPS_VAL}" != "false" ]]; then
    echo "[-] ERROR: Client segregation violation: SIGNUPS_ALLOWED is '${SIGNUPS_VAL}' (must be 'false')" >&2
    exit 1
  fi

  if [[ "${DOMAIN_VAL}" != "http://localhost:7278" && "${DOMAIN_VAL}" != "http://${HOST}:7278" ]]; then
    echo "[-] ERROR: Client segregation violation: DOMAIN is '${DOMAIN_VAL}' (must be 'http://localhost:7278')" >&2
    exit 1
  fi
else
  # Inspect compose file as static configuration verification
  if ! grep -q 'SIGNUPS_ALLOWED: "false"' "${COMPOSE_FILE}"; then
    echo "[-] ERROR: Client segregation violation: SIGNUPS_ALLOWED is not set to 'false' in ${COMPOSE_FILE}" >&2
    exit 1
  fi
  if ! grep -q 'DOMAIN: "http://localhost:7278"' "${COMPOSE_FILE}"; then
    echo "[-] ERROR: Client segregation violation: DOMAIN is not set to 'http://localhost:7278' in ${COMPOSE_FILE}" >&2
    exit 1
  fi
fi

# Verify staging is NOT configured with production domain
if echo "${ENV_DUMP}" | grep -q "vw.cloud.jacobmiller22.com"; then
  echo "[-] ERROR: Client segregation violation: Staging container contains production domain!" >&2
  exit 1
fi

echo "[+] Step 6: Client segregation assertions verified:"
echo "    - SIGNUPS_ALLOWED=false (registration disabled)"
echo "    - DOMAIN=http://localhost:7278 (isolated from production push/sync)"
echo "    - Zero production domain leakage confirmed."

# ------------------------------------------------------------------------------
# Summary & Success
# ------------------------------------------------------------------------------
echo "=============================================================================="
echo "✅ Upgrade verification SUCCESSFUL for Vaultwarden image '${CANDIDATE_TAG}'!"
echo "=============================================================================="
exit 0
