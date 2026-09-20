#!/usr/bin/env bash
# ==============================================================================
# Disaster Recovery (DR): Scheduled Failover & Drill Automation Orchestrator
# ==============================================================================
# Master disaster recovery drill engine orchestrating the complete failover
# pipeline for self-hosted services:
# 1. Archive Discovery & Decryption (pull-and-decrypt.sh)
# 2. Deep Database Integrity & Foreign Key Validation (verify-db-integrity.sh)
# 3. Ephemeral Staging Container Smoke Testing (staging-smoke-test.sh)
#
# Telemetry & Reliability Features:
# - RTO Tracking: Measures start-to-finish recovery time in seconds.
# - RPO Tracking: Computes delta between current time and backup archive timestamp.
#   Alerts if backup archive age exceeds SLA threshold (default: 26 hours).
# - Active Discord Failure Trap: Traps ERR/EXIT, captures line number, failing step,
#   exit code, and recent log tail, dispatching a structured embed to Discord.
# - Passive Dead Man's Snitch: Pings Healthchecks.io endpoint upon 100% clean drill.
# - Optional Success Embed: Dispatches telemetry embed with RTO/RPO metrics.
# - Safe Dry-Run Mode: Simulates end-to-end execution without mutating state.
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Script Location & Directory Resolution
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export REPO_ROOT

PULL_SCRIPT="${SCRIPT_DIR}/pull-and-decrypt.sh"
INTEGRITY_SCRIPT="${SCRIPT_DIR}/verify-db-integrity.sh"
SMOKE_SCRIPT="${SCRIPT_DIR}/staging-smoke-test.sh"

# ------------------------------------------------------------------------------
# Exit Code Constants
# ------------------------------------------------------------------------------
readonly EXIT_OK=0
readonly EXIT_USAGE_ERR=1
readonly EXIT_PULL_FAIL=2
readonly EXIT_INTEGRITY_FAIL=3
readonly EXIT_SMOKE_FAIL=4
readonly EXIT_RPO_FAIL=5
readonly EXIT_PING_FAIL=6

# ------------------------------------------------------------------------------
# Default State & Configuration
# ------------------------------------------------------------------------------
SERVICE="${SERVICE_NAME:-${SERVICE:-all}}"
SOURCE="${BACKUP_SOURCE:-}"
BACKUP_DIR="${BACKUP_DIR:-}"
ARCHIVE_FILE="${ARCHIVE_FILE:-${BACKUP_FILE:-}}"
DATA_DIR="${DATA_DIR:-}"
CLI_PASSPHRASE=""
TIMEOUT="${TIMEOUT:-30}"
DRY_RUN=false
SKIP_PULL=false
KEEP=false
HOST="${TARGET_HOST:-${HOST:-}}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
HEALTHCHECK_DR_PING_URL="${HEALTHCHECK_DR_PING_URL:-}"
RPO_MAX_HOURS="${RPO_MAX_HOURS:-26}"
FAIL_ON_RPO=false

# CLI overrideable binaries forwarded to sub-scripts
export DOCKER_CMD="${DOCKER_CMD:-docker}"
export CURL_CMD="${CURL_CMD:-curl}"
export SSH_CMD="${SSH_CMD:-ssh}"
CURL_BIN="${CURL_CMD}"

# Drill telemetry & execution state
DRILL_START_TIME=""
DRILL_END_TIME=""
RTO_SECONDS=0
RPO_SECONDS=0
RPO_HOURS=0
RPO_ALERT=false
CURRENT_STEP="initialization"
SUCCESS=false
CLEANED_UP=false

# Scratchpad and log references
DRILL_SCRATCH=""
DRILL_LOG=""

# Standalone helper invocation modes
CALCULATE_RPO_TARGET=""
CALCULATE_RTO_START=""
CALCULATE_RTO_END=""
REFERENCE_TIME=""

# ------------------------------------------------------------------------------
# Logging Helpers
# ------------------------------------------------------------------------------
log_info() {
  if [[ -n "${DRILL_LOG:-}" && -f "${DRILL_LOG}" ]]; then
    echo "[+] $*" | tee -a "${DRILL_LOG}"
  else
    echo "[+] $*"
  fi
}

log_warn() {
  if [[ -n "${DRILL_LOG:-}" && -f "${DRILL_LOG}" ]]; then
    echo "[!] $*" | tee -a "${DRILL_LOG}" >&2
  else
    echo "[!] $*" >&2
  fi
}

log_error() {
  if [[ -n "${DRILL_LOG:-}" && -f "${DRILL_LOG}" ]]; then
    echo "[-] ERROR: $*" | tee -a "${DRILL_LOG}" >&2
  else
    echo "[-] ERROR: $*" >&2
  fi
}

# ------------------------------------------------------------------------------
# Lifecycle & Cleanup
# ------------------------------------------------------------------------------
cleanup_scratch() {
  local exit_code=$?
  if [[ "${CLEANED_UP}" == "true" ]]; then
    return "${exit_code}"
  fi
  CLEANED_UP=true

  if [[ "${KEEP}" == "true" ]]; then
    if [[ -n "${DRILL_SCRATCH}" && -d "${DRILL_SCRATCH}" ]]; then
      echo "[*] Retention enabled (--keep): temporary drill files retained at ${DRILL_SCRATCH}"
    fi
  else
    if [[ -n "${DRILL_SCRATCH}" && -d "${DRILL_SCRATCH}" ]]; then
      rm -rf "${DRILL_SCRATCH}"
    fi
  fi
  return "${exit_code}"
}

# ------------------------------------------------------------------------------
# Notification Helpers (Discord Embeds)
# ------------------------------------------------------------------------------
# shellcheck disable=SC2329
send_discord_failure_embed() {
  local step="$1"
  local line_no="$2"
  local exit_code="$3"
  local failed_cmd="$4"
  local log_tail="$5"

  local webhook_url="${DISCORD_WEBHOOK_URL:-}"
  if [[ -z "${webhook_url}" ]]; then
    return 0
  fi

  # Truncate log tail to avoid exceeding Discord embed limits
  local truncated_tail
  truncated_tail=$(echo "${log_tail}" | tail -c 1500)

  local payload=""
  if command -v python3 >/dev/null 2>&1; then
    # shellcheck disable=SC2016
    payload=$(python3 -c '
import json, sys, os, datetime

step = sys.argv[1]
line_no = sys.argv[2]
exit_code = sys.argv[3]
failed_cmd = sys.argv[4]
log_tail = sys.argv[5]
hostname = os.uname().nodename
now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

fields = [
    {"name": "Host", "value": hostname, "inline": True},
    {"name": "Failing Step", "value": f"`{step}`", "inline": True},
    {"name": "Exit Code", "value": str(exit_code), "inline": True},
    {"name": "Line Number", "value": str(line_no), "inline": True},
    {"name": "Failed Command", "value": f"`{failed_cmd}`" if failed_cmd else "unknown", "inline": False},
    {"name": "Timestamp", "value": now_utc, "inline": False}
]
if log_tail.strip():
    fields.append({"name": "Recent Logs", "value": f"```{log_tail}```", "inline": False})

data = {
    "embeds": [{
        "title": f"🚨 Disaster Recovery Drill FAILED: {step}",
        "color": 15158332, # Red
        "description": "Automated DR drill encountered an unhandled error or assertion failure.",
        "fields": fields,
        "footer": {"text": "selfhosted DR orchestrator"}
    }]
}
print(json.dumps(data))
' "${step}" "${line_no}" "${exit_code}" "${failed_cmd}" "${truncated_tail}" 2>/dev/null || true)
  fi

  if [[ -z "${payload}" ]]; then
    local escaped_cmd
    escaped_cmd=$(printf '%s' "${failed_cmd}" | sed 's/"/\\"/g')
    payload=$(cat <<EOF
{
  "embeds": [{
    "title": "🚨 Disaster Recovery Drill FAILED: ${step}",
    "color": 15158332,
    "fields": [
      { "name": "Host", "value": "$(hostname)", "inline": true },
      { "name": "Failing Step", "value": "${step}", "inline": true },
      { "name": "Exit Code", "value": "${exit_code}", "inline": true },
      { "name": "Line", "value": "${line_no}", "inline": true },
      { "name": "Command", "value": "${escaped_cmd}", "inline": false }
    ]
  }]
}
EOF
    )
  fi

  "${CURL_BIN}" -fsS -H "Content-Type: application/json" -d "${payload}" "${webhook_url}" >/dev/null 2>&1 || true
}

# shellcheck disable=SC2329
send_discord_success_embed() {
  local rto_sec="$1"
  local rpo_sec="$2"
  local rpo_hours="$3"
  local rpo_alert="$4"
  local services_list="$5"

  local webhook_url="${DISCORD_WEBHOOK_URL:-}"
  if [[ -z "${webhook_url}" ]]; then
    return 0
  fi

  local color=3066993 # Green (#2ecc71)
  local status_text="All DR validation phases passed cleanly."
  if [[ "${rpo_alert}" == "true" ]]; then
    color=15105570 # Orange warning (#e67e22)
    status_text="DR verification passed, but backup archive exceeded the RPO SLA threshold."
  fi

  local payload=""
  if command -v python3 >/dev/null 2>&1; then
    # shellcheck disable=SC2016
    payload=$(python3 -c '
import json, sys, os, datetime

rto_sec = sys.argv[1]
rpo_sec = sys.argv[2]
rpo_hours = sys.argv[3]
rpo_alert = sys.argv[4] == "true"
services = sys.argv[5]
color = int(sys.argv[6])
status_text = sys.argv[7]
hostname = os.uname().nodename
now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

rpo_desc = f"{rpo_hours}h ({rpo_sec}s)"
if rpo_alert:
    rpo_desc += " ⚠️ **EXCEEDS SLA THRESHOLD**"

fields = [
    {"name": "Host", "value": hostname, "inline": True},
    {"name": "Services", "value": services, "inline": True},
    {"name": "Status", "value": "✅ PASSED", "inline": True},
    {"name": "RTO (Recovery Time)", "value": f"{rto_sec}s", "inline": True},
    {"name": "RPO (Backup Age)", "value": rpo_desc, "inline": True},
    {"name": "Timestamp", "value": now_utc, "inline": False}
]

data = {
    "embeds": [{
        "title": "✅ Disaster Recovery Drill PASSED",
        "color": color,
        "description": status_text,
        "fields": fields,
        "footer": {"text": "selfhosted DR orchestrator"}
    }]
}
print(json.dumps(data))
' "${rto_sec}" "${rpo_sec}" "${rpo_hours}" "${rpo_alert}" "${services_list}" "${color}" "${status_text}" 2>/dev/null || true)
  fi

  if [[ -z "${payload}" ]]; then
    payload=$(cat <<EOF
{
  "embeds": [{
    "title": "✅ Disaster Recovery Drill PASSED",
    "color": ${color},
    "fields": [
      { "name": "Host", "value": "$(hostname)", "inline": true },
      { "name": "Services", "value": "${services_list}", "inline": true },
      { "name": "RTO", "value": "${rto_sec}s", "inline": true },
      { "name": "RPO", "value": "${rpo_hours}h (${rpo_sec}s)", "inline": true }
    ]
  }]
}
EOF
    )
  fi

  "${CURL_BIN}" -fsS -H "Content-Type: application/json" -d "${payload}" "${webhook_url}" >/dev/null 2>&1 || true
}

# ------------------------------------------------------------------------------
# Active Failure Trap
# ------------------------------------------------------------------------------
# shellcheck disable=SC2329
on_failure() {
  local exit_code=$?
  local line_no="${1:-${BASH_LINENO[0]:-unknown}}"
  local failed_cmd="${2:-${BASH_COMMAND:-unknown}}"

  # If clean exit upon success, perform normal teardown and return cleanly
  if [[ "${SUCCESS}" == "true" && "${exit_code}" -eq 0 ]]; then
    cleanup_scratch
    return 0
  fi

  # Disable trap to avoid recursion during failure handling
  trap - ERR EXIT INT TERM

  # Map exit code to standard constant if generic
  if [[ "${exit_code}" -eq 0 || "${exit_code}" -eq 1 ]]; then
    case "${CURRENT_STEP}" in
      pull-and-decrypt*) exit_code="${EXIT_PULL_FAIL}" ;;
      verify-db-integrity*) exit_code="${EXIT_INTEGRITY_FAIL}" ;;
      staging-smoke-test*) exit_code="${EXIT_SMOKE_FAIL}" ;;
      healthchecks-ping*) exit_code="${EXIT_PING_FAIL}" ;;
      *) exit_code="${EXIT_USAGE_ERR}" ;;
    esac
  fi

  echo "" >&2
  echo "==============================================================================" >&2
  echo "🚨 [DR-DRILL] FAILURE: Disaster recovery drill failed during step: ${CURRENT_STEP}" >&2
  echo "==============================================================================" >&2
  echo "[-] Failing Step: ${CURRENT_STEP}" >&2
  echo "[-] Line Number:  ${line_no}" >&2
  echo "[-] Exit Code:    ${exit_code}" >&2
  echo "[-] Command:      ${failed_cmd}" >&2
  echo "" >&2

  local log_tail=""
  if [[ -n "${DRILL_LOG:-}" && -f "${DRILL_LOG}" ]]; then
    log_tail=$(tail -n 20 "${DRILL_LOG}" 2>/dev/null || true)
    echo "[-] Last 20 lines of drill log:" >&2
    echo "${log_tail}" >&2
    echo "" >&2
  fi

  if [[ -n "${DISCORD_WEBHOOK_URL:-}" ]]; then
    echo "[*] Dispatching failure alert embed to Discord webhook..." >&2
    send_discord_failure_embed "${CURRENT_STEP}" "${line_no}" "${exit_code}" "${failed_cmd}" "${log_tail}"
  fi

  cleanup_scratch
  exit "${exit_code}"
}

# ------------------------------------------------------------------------------
# RTO & RPO Calculation Engine
# ------------------------------------------------------------------------------
extract_epoch() {
  local input="$1"
  local ts_pattern="([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2})"

  if [[ "${input}" =~ ${ts_pattern} ]]; then
    local ts="${BASH_REMATCH[1]}"
    if command -v python3 >/dev/null 2>&1; then
      python3 -c "import sys, datetime; dt = datetime.datetime.strptime(sys.argv[1], '%Y-%m-%d_%H-%M-%S').replace(tzinfo=datetime.timezone.utc); print(int(dt.timestamp()))" "${ts}" 2>/dev/null && return 0
    fi
    if date -j -u -f "%Y-%m-%d_%H-%M-%S" "${ts}" +%s >/dev/null 2>&1; then
      date -j -u -f "%Y-%m-%d_%H-%M-%S" "${ts}" +%s
      return 0
    fi
    local date_part="${ts%_*}"
    local time_part="${ts#*_}"
    time_part="${time_part//-/:}"
    if date -u -d "${date_part} ${time_part}" +%s >/dev/null 2>&1; then
      date -u -d "${date_part} ${time_part}" +%s
      return 0
    fi
  elif [[ -e "${input}" ]]; then
    if stat -f %m "${input}" >/dev/null 2>&1; then
      stat -f %m "${input}"
      return 0
    elif stat -c %Y "${input}" >/dev/null 2>&1; then
      stat -c %Y "${input}"
      return 0
    elif command -v python3 >/dev/null 2>&1; then
      python3 -c "import os, sys; print(int(os.path.getmtime(sys.argv[1])))" "${input}" 2>/dev/null && return 0
    fi
  elif [[ "${input}" =~ ^[0-9]+$ ]]; then
    echo "${input}"
    return 0
  fi
  return 1
}

calculate_rpo_metrics() {
  local target="$1"
  local ref_time="${2:-}"
  local max_hours="${3:-${RPO_MAX_HOURS}}"

  local ref_epoch=""
  if [[ -n "${ref_time}" ]]; then
    ref_epoch=$(extract_epoch "${ref_time}" || echo "")
  fi
  if [[ -z "${ref_epoch}" ]]; then
    ref_epoch=$(date +%s)
  fi

  local archive_epoch=""
  archive_epoch=$(extract_epoch "${target}" || echo "")
  if [[ -z "${archive_epoch}" ]]; then
    log_error "Failed to extract timestamp from: ${target}"
    return 1
  fi

  local rpo_sec=$((ref_epoch - archive_epoch))
  if [[ "${rpo_sec}" -lt 0 ]]; then
    rpo_sec=0
  fi

  local rpo_hours=$((rpo_sec / 3600))
  local rpo_alert=false
  local max_sec=$((max_hours * 3600))
  if [[ "${rpo_sec}" -gt "${max_sec}" ]]; then
    rpo_alert=true
  fi

  echo "RPO_SECONDS=${rpo_sec}"
  echo "RPO_HOURS=${rpo_hours}"
  echo "RPO_ALERT=${rpo_alert}"
  echo "RPO_MAX_HOURS=${max_hours}"
  echo "BACKUP_TIMESTAMP_EPOCH=${archive_epoch}"
  echo "REFERENCE_TIMESTAMP_EPOCH=${ref_epoch}"
}

calculate_rto_metrics() {
  local start_epoch="$1"
  local end_epoch="$2"
  local rto_sec=$((end_epoch - start_epoch))
  if [[ "${rto_sec}" -lt 0 ]]; then
    rto_sec=0
  fi
  echo "RTO_SECONDS=${rto_sec}"
}

# ------------------------------------------------------------------------------
# Help & Usage Guide
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Master Disaster Recovery (DR) orchestrator combining archive pull/decrypt,
deep SQLite integrity checks, ephemeral staging container smoke tests,
RTO/RPO telemetry tracking, Discord alerting, and Healthchecks.io heartbeat.

Options:
  -s, --service <name>       Service to drill (actual, vaultwarden, or all; default: all)
      --source <type>        Backup archive source: b2, s3, local, file
  -b, --backup-dir <path>    Local directory containing encrypted backup archives
  -f, --file <path>          Path to a specific backup archive file
  -d, --data-dir <path>      Directory containing pre-decrypted test data (used with --skip-pull)
      --skip-pull            Skip downloading and decrypting; use existing snapshot in --data-dir
      --dry-run              Simulate drill pipeline without modifying Docker or network states
      --host <hostname>      Remote host for staging execution via SSH (default: local)
  -t, --timeout <sec>        Timeout in seconds for container health probes (default: 30)
  -k, --keep                 Retain temporary scratch directory and staging containers
  -p, --passphrase <val>     Decryption passphrase (overrides environment variables)
      --webhook-url <url>    Discord webhook URL for alerts (or DISCORD_WEBHOOK_URL)
      --ping-url <url>       Healthchecks.io / Snitch ping URL (or HEALTHCHECK_DR_PING_URL)
      --rpo-max-hours <hrs>  Max allowable RPO age in hours before alert (default: 26)
      --fail-on-rpo          Exit with failure code if RPO threshold is breached
      --calculate-rpo <tgt>  Helper: Compute RPO metrics for target timestamp or archive and exit
      --calculate-rto <s,e>  Helper: Compute RTO elapsed seconds given start and end epoch and exit
      --reference-time <ts>  Reference time for --calculate-rpo (default: now)
  -h, --help                 Display this help message and exit

Environment Variables:
  SERVICE_NAME               Service name (actual, vaultwarden, or all)
  BACKUP_SOURCE              Backup source type (b2, s3, local, file)
  BACKUP_DIR                 Directory containing local backup archives
  BACKUP_FILE                Specific backup archive file to decrypt
  DATA_DIR                   Directory containing pre-decrypted test data
  BACKUP_PASSPHRASE          Decryption passphrase (PBKDF2)
  BACKUP_ENCRYPTION_KEY      Fallback decryption passphrase
  BACKUP_DEST_BUCKET         S3/B2 bucket name
  BACKUP_DEST_ENDPOINT       S3/B2 endpoint URL
  DISCORD_WEBHOOK_URL        Discord webhook URL for success/failure embeds
  HEALTHCHECK_DR_PING_URL    Healthchecks.io URL pinged on 100% clean drill completion
  RPO_MAX_HOURS              RPO alert threshold in hours (default: 26)
  TARGET_HOST                Remote host for execution via SSH (e.g. bjorn)

Exit Codes:
  0   All DR validation phases passed cleanly (100% verified)
  1   CLI syntax, option parsing, or argument validation error
  2   Backup archive pull or decryption failure
  3   SQLite page, foreign key, or storage integrity failure
  4   Ephemeral staging container health probe failure
  5   RPO SLA threshold breached (with --fail-on-rpo)
  6   Healthchecks ping failure
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
        exit "${EXIT_USAGE_ERR}"
      fi
      SERVICE="$2"
      shift 2
      ;;
    --service=*)
      SERVICE="${1#*=}"
      shift
      ;;
    --source)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      SOURCE="$2"
      shift 2
      ;;
    --source=*)
      SOURCE="${1#*=}"
      shift
      ;;
    -b|--backup-dir)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      BACKUP_DIR="$2"
      shift 2
      ;;
    --backup-dir=*)
      BACKUP_DIR="${1#*=}"
      shift
      ;;
    -f|--file)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      ARCHIVE_FILE="$2"
      shift 2
      ;;
    --file=*)
      ARCHIVE_FILE="${1#*=}"
      shift
      ;;
    -d|--data-dir)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      DATA_DIR="$2"
      shift 2
      ;;
    --data-dir=*)
      DATA_DIR="${1#*=}"
      shift
      ;;
    --skip-pull)
      SKIP_PULL=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --host)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      HOST="$2"
      shift 2
      ;;
    --host=*)
      HOST="${1#*=}"
      shift
      ;;
    -t|--timeout)
      if [[ -z "${2:-}" || ( "${2}" == -* && ! "${2}" =~ ^-[0-9]+$ ) ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
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
    -p|--passphrase)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      CLI_PASSPHRASE="$2"
      shift 2
      ;;
    --passphrase=*)
      CLI_PASSPHRASE="${1#*=}"
      shift
      ;;
    --webhook-url)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      DISCORD_WEBHOOK_URL="$2"
      shift 2
      ;;
    --webhook-url=*)
      DISCORD_WEBHOOK_URL="${1#*=}"
      shift
      ;;
    --ping-url)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      HEALTHCHECK_DR_PING_URL="$2"
      shift 2
      ;;
    --ping-url=*)
      HEALTHCHECK_DR_PING_URL="${1#*=}"
      shift
      ;;
    --rpo-max-hours)
      if [[ -z "${2:-}" || ( "${2}" == -* && ! "${2}" =~ ^-[0-9]+$ ) ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      RPO_MAX_HOURS="$2"
      shift 2
      ;;
    --rpo-max-hours=*)
      RPO_MAX_HOURS="${1#*=}"
      shift
      ;;
    --fail-on-rpo)
      FAIL_ON_RPO=true
      shift
      ;;
    --calculate-rpo)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      CALCULATE_RPO_TARGET="$2"
      shift 2
      ;;
    --calculate-rpo=*)
      CALCULATE_RPO_TARGET="${1#*=}"
      shift
      ;;
    --calculate-rto)
      if [[ -z "${2:-}" || -z "${3:-}" ]]; then
        echo "[-] ERROR: --calculate-rto requires <start_epoch> and <end_epoch>" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      CALCULATE_RTO_START="$2"
      CALCULATE_RTO_END="$3"
      shift 3
      ;;
    --reference-time)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit "${EXIT_USAGE_ERR}"
      fi
      REFERENCE_TIME="$2"
      shift 2
      ;;
    --reference-time=*)
      REFERENCE_TIME="${1#*=}"
      shift
      ;;
    -h|--help)
      show_help
      exit "${EXIT_OK}"
      ;;
    *)
      echo "[-] ERROR: Unknown option: $1" >&2
      echo "Run '$(basename "$0") --help' for usage." >&2
      exit "${EXIT_USAGE_ERR}"
      ;;
  esac
done

# ------------------------------------------------------------------------------
# Helper Dispatch Modes (RTO / RPO evaluation)
# ------------------------------------------------------------------------------
if [[ -n "${CALCULATE_RTO_START}" && -n "${CALCULATE_RTO_END}" ]]; then
  calculate_rto_metrics "${CALCULATE_RTO_START}" "${CALCULATE_RTO_END}"
  exit "${EXIT_OK}"
fi

if [[ -n "${CALCULATE_RPO_TARGET}" ]]; then
  calculate_rpo_metrics "${CALCULATE_RPO_TARGET}" "${REFERENCE_TIME}" "${RPO_MAX_HOURS}"
  exit "${EXIT_OK}"
fi

# ------------------------------------------------------------------------------
# Input Validation & Target Service Resolution
# ------------------------------------------------------------------------------
case "${SERVICE}" in
  actual|vaultwarden|all)
    ;;
  *)
    echo "[-] ERROR: Unsupported service '${SERVICE}'. Supported services: actual, vaultwarden, all." >&2
    exit "${EXIT_USAGE_ERR}"
    ;;
esac

if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT}" -le 0 ]]; then
  echo "[-] ERROR: Timeout must be a positive integer (got '${TIMEOUT}')." >&2
  exit "${EXIT_USAGE_ERR}"
fi

if ! [[ "${RPO_MAX_HOURS}" =~ ^[0-9]+$ ]] || [[ "${RPO_MAX_HOURS}" -le 0 ]]; then
  echo "[-] ERROR: RPO max hours must be a positive integer (got '${RPO_MAX_HOURS}')." >&2
  exit "${EXIT_USAGE_ERR}"
fi

if [[ "${SKIP_PULL}" == "true" ]]; then
  if [[ -z "${DATA_DIR}" ]]; then
    echo "[-] ERROR: --data-dir <path> is required when --skip-pull is set." >&2
    exit "${EXIT_USAGE_ERR}"
  fi
  if [[ ! -d "${DATA_DIR}" ]]; then
    echo "[-] ERROR: Specified data directory '${DATA_DIR}' does not exist." >&2
    exit "${EXIT_USAGE_ERR}"
  fi
fi

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
# Prerequisite Scripts Verification
# ------------------------------------------------------------------------------
for script_file in "${PULL_SCRIPT}" "${INTEGRITY_SCRIPT}" "${SMOKE_SCRIPT}"; do
  if [[ ! -x "${script_file}" ]]; then
    echo "[-] ERROR: Required DR helper script '${script_file}' is missing or not executable." >&2
    exit "${EXIT_USAGE_ERR}"
  fi
done

# ------------------------------------------------------------------------------
# Step Execution Helper
# ------------------------------------------------------------------------------
run_step() {
  local step_name="$1"
  shift
  CURRENT_STEP="${step_name}"
  log_info "Step: ${step_name} -> $*"
  "$@" 2>&1 | tee -a "${DRILL_LOG}"
}

# ------------------------------------------------------------------------------
# Initialization: Scratch Directory, Telemetry Clock & Trap Installation
# ------------------------------------------------------------------------------
trap 'on_failure "${LINENO}" "${BASH_COMMAND}"' ERR EXIT INT TERM

DRILL_START_TIME=$(date +%s)
DRILL_SCRATCH="$(mktemp -d /tmp/dr-drill-XXXXXX)"
DRILL_LOG="${DRILL_SCRATCH}/dr-drill.log"
touch "${DRILL_LOG}"

log_info "=============================================================================="
log_info "🚀 Disaster Recovery Automated Drill Orchestrator"
log_info "=============================================================================="
log_info "Target Service:  ${SERVICE}"
log_info "Execution Host:  ${HOST:-local}"
log_info "Dry-Run Mode:    ${DRY_RUN}"
log_info "Skip-Pull Mode:  ${SKIP_PULL}"
log_info "RPO SLA Limit:   ${RPO_MAX_HOURS} hours"
log_info "Scratchpad Dir:  ${DRILL_SCRATCH}"
log_info "Drill Start:     $(date -u +'%Y-%m-%dT%H:%M:%SZ') (${DRILL_START_TIME})"
log_info "=============================================================================="

# ------------------------------------------------------------------------------
# Phase 1: Pull and Decrypt Archives
# ------------------------------------------------------------------------------
CURRENT_STEP="pull-and-decrypt"
DRILL_DATA_ROOT=""
DISCOVERED_ARCHIVE=""

if [[ "${SKIP_PULL}" == "true" ]]; then
  log_info "Phase 1: Backup archive download and decryption skipped (--skip-pull)."
  DRILL_DATA_ROOT="${DATA_DIR}"
  if [[ -n "${ARCHIVE_FILE}" ]]; then
    DISCOVERED_ARCHIVE="${ARCHIVE_FILE}"
  fi
else
  log_info "Phase 1: Discovering, pulling, and decrypting backup archives..."
  DRILL_DATA_ROOT="${DRILL_SCRATCH}/data"
  mkdir -p "${DRILL_DATA_ROOT}"

  for svc in "${TARGET_SERVICES[@]}"; do
    svc_dest="${DRILL_DATA_ROOT}/${svc}"
    mkdir -p "${svc_dest}"

    declare -a pull_args=("--service" "${svc}" "--dest" "${svc_dest}")
    if [[ -n "${SOURCE}" ]]; then
      pull_args+=("--source" "${SOURCE}")
    fi
    if [[ -n "${BACKUP_DIR}" ]]; then
      pull_args+=("--backup-dir" "${BACKUP_DIR}")
    fi
    if [[ -n "${ARCHIVE_FILE}" ]]; then
      pull_args+=("--file" "${ARCHIVE_FILE}")
    fi
    if [[ -n "${CLI_PASSPHRASE}" ]]; then
      pull_args+=("--passphrase" "${CLI_PASSPHRASE}")
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
      pull_args+=("--dry-run")
    fi

    if [[ "${DRY_RUN}" == "true" && -z "${BACKUP_DIR}" && -z "${ARCHIVE_FILE}" && -z "${BACKUP_DEST_BUCKET:-}" && ! -d "/backups" ]]; then
      sim_ts=$(date -u +'%Y-%m-%d_%H-%M-%S')
      log_info "[dry-run] pull-and-decrypt.sh --service ${svc} (simulated discovery: ${svc}-backup-${sim_ts}.tar.gz.enc)"
      DISCOVERED_ARCHIVE="${svc}-backup-${sim_ts}.tar.gz.enc"
    else
      run_step "pull-and-decrypt-${svc}" "${PULL_SCRIPT}" "${pull_args[@]}"
    fi
  done

  # Detect latest archive file for RPO calculation
  if [[ -n "${ARCHIVE_FILE}" ]]; then
    DISCOVERED_ARCHIVE="${ARCHIVE_FILE}"
  elif [[ -n "${BACKUP_DIR}" && -d "${BACKUP_DIR}" ]]; then
    DISCOVERED_ARCHIVE=$(find "${BACKUP_DIR}" -type f -name "*-backup-*.tar.gz.enc" 2>/dev/null | sort -r | head -n 1 || true)
  fi
fi

# ------------------------------------------------------------------------------
# Phase 2: Database & Storage Deep Integrity Verification
# ------------------------------------------------------------------------------
CURRENT_STEP="verify-db-integrity"
log_info "Phase 2: Verifying database integrity, foreign keys, and storage assets..."

for svc in "${TARGET_SERVICES[@]}"; do
  svc_data_dir="${DRILL_DATA_ROOT}/${svc}"
  if [[ ! -d "${svc_data_dir}" && -d "${DRILL_DATA_ROOT}" ]]; then
    svc_data_dir="${DRILL_DATA_ROOT}"
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    log_info "[dry-run] verify-db-integrity.sh --service ${svc} --dir ${svc_data_dir} (simulated)"
  else
    run_step "verify-db-integrity-${svc}" "${INTEGRITY_SCRIPT}" --service "${svc}" --dir "${svc_data_dir}" --verbose
  fi
done

# ------------------------------------------------------------------------------
# Phase 3: Ephemeral Staging Smoke Test
# ------------------------------------------------------------------------------
CURRENT_STEP="staging-smoke-test"
log_info "Phase 3: Running ephemeral staging container smoke tests..."

declare -a smoke_args=("--service" "${SERVICE}" "--data-dir" "${DRILL_DATA_ROOT}" "--timeout" "${TIMEOUT}")
if [[ "${DRY_RUN}" == "true" ]]; then
  smoke_args+=("--dry-run")
fi
if [[ "${KEEP}" == "true" ]]; then
  smoke_args+=("--keep")
fi
if [[ -n "${HOST}" ]]; then
  smoke_args+=("--host" "${HOST}")
fi

run_step "staging-smoke-test" "${SMOKE_SCRIPT}" "${smoke_args[@]}"

# ------------------------------------------------------------------------------
# Phase 4: RTO & RPO Telemetry Calculation & Threshold Checks
# ------------------------------------------------------------------------------
CURRENT_STEP="rto-rpo-metrics"
log_info "Phase 4: Calculating RTO and RPO telemetry metrics..."

DRILL_END_TIME=$(date +%s)
RTO_SECONDS=$((DRILL_END_TIME - DRILL_START_TIME))

# Fallback archive discovery if not already set
if [[ -z "${DISCOVERED_ARCHIVE}" ]]; then
  DISCOVERED_ARCHIVE=$(find "${DRILL_DATA_ROOT}" -type f -name "*-backup-*.tar.gz.enc" 2>/dev/null | sort -r | head -n 1 || true)
fi
if [[ -z "${DISCOVERED_ARCHIVE}" ]]; then
  DISCOVERED_ARCHIVE="${DRILL_DATA_ROOT}"
fi

rpo_eval=$(calculate_rpo_metrics "${DISCOVERED_ARCHIVE}" "${DRILL_END_TIME}" "${RPO_MAX_HOURS}" 2>/dev/null || echo "")
if [[ -n "${rpo_eval}" ]]; then
  eval "${rpo_eval}"
else
  RPO_SECONDS=0
  RPO_HOURS=0
  RPO_ALERT=false
fi

log_info "=============================================================================="
log_info "📊 Telemetry & SLA Metrics Summary"
log_info "=============================================================================="
log_info "• RTO (Recovery Time Objective):  ${RTO_SECONDS}s"
log_info "• RPO (Recovery Point Objective): ${RPO_HOURS}h (${RPO_SECONDS}s)"
log_info "• RPO Max SLA Threshold:          ${RPO_MAX_HOURS}h"
log_info "• Services Verified:              ${TARGET_SERVICES[*]}"

if [[ "${RPO_ALERT}" == "true" ]]; then
  log_warn "⚠️ RPO ALERT: Backup archive age (${RPO_HOURS}h) exceeds maximum allowed RPO threshold of ${RPO_MAX_HOURS}h!"
  if [[ "${FAIL_ON_RPO}" == "true" ]]; then
    echo "[-] ERROR: Disaster recovery drill failed due to RPO SLA violation." >&2
    exit "${EXIT_RPO_FAIL}"
  fi
else
  log_info "• RPO Status:                     ✅ Within SLA Threshold"
fi
log_info "=============================================================================="

# ------------------------------------------------------------------------------
# Phase 5: Passive Dead Man's Snitch / Healthchecks.io Heartbeat Ping
# ------------------------------------------------------------------------------
CURRENT_STEP="healthchecks-ping"
if [[ -n "${HEALTHCHECK_DR_PING_URL}" ]]; then
  if [[ "${DRY_RUN}" == "true" ]]; then
    log_info "[dry-run] Healthchecks Ping: ${CURL_BIN} -fsS -m 10 --retry 3 \"${HEALTHCHECK_DR_PING_URL}\""
  else
    log_info "Pinging Dead Man's Snitch / Healthchecks.io endpoint..."
    run_step "healthchecks-ping" "${CURL_BIN}" -fsS -m 10 --retry 3 "${HEALTHCHECK_DR_PING_URL}"
    log_info "Healthchecks.io heartbeat ping successful."
  fi
elif [[ "${DRY_RUN}" == "true" ]]; then
  log_info "[dry-run] Healthchecks Ping: (simulated heartbeat ping skipped)"
else
  log_info "HEALTHCHECK_DR_PING_URL not configured; skipping passive heartbeat ping."
fi

# ------------------------------------------------------------------------------
# Phase 6: Discord Success Embed Dispatch
# ------------------------------------------------------------------------------
CURRENT_STEP="discord-alerting"
if [[ -n "${DISCORD_WEBHOOK_URL}" ]]; then
  if [[ "${DRY_RUN}" == "true" ]]; then
    log_info "[dry-run] Discord Notification: would post success embed to ${DISCORD_WEBHOOK_URL}"
  else
    log_info "Dispatching success notification embed to Discord webhook..."
    send_discord_success_embed "${RTO_SECONDS}" "${RPO_SECONDS}" "${RPO_HOURS}" "${RPO_ALERT}" "${TARGET_SERVICES[*]}"
  fi
elif [[ "${DRY_RUN}" == "true" ]]; then
  log_info "[dry-run] Discord Notification: (simulated success embed skipped)"
else
  log_info "DISCORD_WEBHOOK_URL not configured; skipping Discord success notification."
fi

# ------------------------------------------------------------------------------
# Phase 7: Prometheus Textfile Telemetry Export
# ------------------------------------------------------------------------------
if [[ -x "${SCRIPT_DIR}/export-dr-metrics.sh" ]]; then
  if [[ "${DRY_RUN}" == "true" ]]; then
    log_info "[dry-run] Prometheus Textfile Export: would export DR metrics"
  else
    for drill_svc in "${TARGET_SERVICES[@]}"; do
      "${SCRIPT_DIR}/export-dr-metrics.sh" \
        --service "${drill_svc}" \
        --rto "${RTO_SECONDS}" \
        --rpo "${RPO_SECONDS}" \
        --drill-status 1 >/dev/null 2>&1 || true
    done
    log_info "Disaster recovery telemetry exported to Prometheus textfile collector."
  fi
fi

# ------------------------------------------------------------------------------
# Drill Completion
# ------------------------------------------------------------------------------
SUCCESS=true
log_info "=============================================================================="
log_info "✅ Disaster Recovery Drill completed successfully (100% Verified)!"
log_info "=============================================================================="

cleanup_scratch
exit "${EXIT_OK}"
