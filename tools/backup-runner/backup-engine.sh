#!/usr/bin/env bash
# ==============================================================================
# Canonical Declarative Backup Engine
# ==============================================================================
# Consolidates all self-hosted service backup operations into a single engine.
#
# Supported Strategies (BACKUP_MODE):
# - sqlite-auto: Automatically scans ${BACKUP_SOURCE_DIR} for any *.sqlite,
#                *.sqlite3, *.db files, performs online snapshots via
#                sqlite3 .backup, copies non-database assets (*.blob, *.pem,
#                *.json, configs), and ignores transient journal files
#                (-wal, -shm, -journal).
# - filesystem:  Recursively stages directory tree without database operations.
# - hook:        Executes a pre-backup hook script (e.g. /hooks/pre-backup.sh)
#                for native CLI dumps (e.g. PostgreSQL pg_dump, CouchDB).
#
# Features:
# - Strict shell safety (set -euo pipefail)
# - Active error trapping (trap 'on_error ...' ERR) with Discord webhook alerts
# - Guaranteed staging directory cleanup on both exit and error (EXIT trap)
# - Zero-dependency OpenSSL AES-256-CBC PBKDF2 (100k iters, SHA-256, salt)
# - Backblaze B2 / S3 rotation via rclone copyto with --s3-no-check-bucket
# - Dead Man's Snitch / Healthchecks.io ping on success
# ==============================================================================

set -euo pipefail

# Source environment variables if running inside container crond
if [[ -f /run/secrets/env_vars ]]; then
  # shellcheck source=/dev/null
  source /run/secrets/env_vars
fi

# ------------------------------------------------------------------------------
# CLI Option Parsing
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Canonical backup runner engine supporting sqlite-auto, filesystem, and hook modes,
with automated OpenSSL AES-256-CBC PBKDF2 encryption, B2/S3 cloud upload, and
retention pruning via rclone.

Options:
  --retention-days <N>   Retention period in days before pruning old snapshots (default: 30)
  --dry-run              Simulate pruning without deleting remote files
  --service <name>       Service identifier (default: unknown-service)
  --mode <mode>          Backup strategy: sqlite-auto, filesystem, hook
  --source-dir <path>    Source directory for sqlite-auto / filesystem modes
  --output-dir <path>    Destination directory for generated encrypted archive
  --b2-dest-path <path>  Explicit remote B2/S3 path (e.g. b2:bucket/prefix)
  --prune-only           Execute remote pruning routine only (requires verified upload or override)
  --help, -h             Display this help message
EOF
}

PRUNE_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --retention-days)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for --retention-days" >&2
        exit 1
      fi
      BACKUP_RETENTION_DAYS="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --service)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for --service" >&2
        exit 1
      fi
      SERVICE_NAME="$2"
      shift 2
      ;;
    --mode)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for --mode" >&2
        exit 1
      fi
      BACKUP_MODE="$2"
      shift 2
      ;;
    --source-dir)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for --source-dir" >&2
        exit 1
      fi
      BACKUP_SOURCE_DIR="$2"
      shift 2
      ;;
    --output-dir)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for --output-dir" >&2
        exit 1
      fi
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --b2-dest-path)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for --b2-dest-path" >&2
        exit 1
      fi
      B2_DEST_PATH="$2"
      shift 2
      ;;
    --prune-only)
      PRUNE_ONLY=true
      shift
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      echo "[-] ERROR: Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# ------------------------------------------------------------------------------
# Configuration & Defaults
# ------------------------------------------------------------------------------
SERVICE_NAME="${SERVICE_NAME:-unknown-service}"
BACKUP_MODE="${BACKUP_MODE:-sqlite-auto}"
BACKUP_SOURCE_DIR="${BACKUP_SOURCE_DIR:-/data}"
PRE_BACKUP_SCRIPT="${PRE_BACKUP_SCRIPT:-${HOOK_SCRIPT:-/hooks/pre-backup.sh}}"

TIMESTAMP="$(date +'%Y-%m-%d_%H-%M-%S')"
STAGING_DIR="${STAGING_DIR:-/tmp/backup-staging-${SERVICE_NAME}-${TIMESTAMP}}"

CLEANUP_OUTPUT_DIR=false
if [[ -z "${OUTPUT_DIR:-}" ]]; then
  OUTPUT_DIR="/tmp/backup-output-${SERVICE_NAME}-${TIMESTAMP}"
  CLEANUP_OUTPUT_DIR=true
fi

BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-${BACKUP_ENCRYPTION_KEY:-}}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
HEALTHCHECK_PING_URL="${HEALTHCHECK_PING_URL:-}"

BACKUP_DEST_ENDPOINT="${BACKUP_DEST_ENDPOINT:-}"
BACKUP_DEST_BUCKET="${BACKUP_DEST_BUCKET:-}"
BACKUP_DEST_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID:-}"
BACKUP_DEST_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY:-}"
BACKUP_DEST_PREFIX="${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME}}"

# Retention & Pruning Configuration
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
DRY_RUN="${DRY_RUN:-false}"
B2_DEST_PATH="${B2_DEST_PATH:-}"

# Normalize DRY_RUN
case "$(echo "${DRY_RUN}" | tr '[:upper:]' '[:lower:]')" in
  true|1|yes) DRY_RUN=true ;;
  *) DRY_RUN=false ;;
esac

# Validate BACKUP_RETENTION_DAYS
if ! [[ "${BACKUP_RETENTION_DAYS}" =~ ^[0-9]+$ ]] || [[ "${BACKUP_RETENTION_DAYS}" -lt 1 ]]; then
  echo "[-] FATAL: Invalid BACKUP_RETENTION_DAYS='${BACKUP_RETENTION_DAYS}'. Must be a positive integer >= 1." >&2
  exit 1
fi

# Upload verification latch state (must be true before pruning will execute)
BACKUP_UPLOAD_VERIFIED="${BACKUP_UPLOAD_VERIFIED:-false}"

# ------------------------------------------------------------------------------
# Guaranteed Cleanup Trap (Exit & Error)
# ------------------------------------------------------------------------------
cleanup() {
  local exit_code=$?
  if [[ -d "${STAGING_DIR}" ]]; then
    rm -rf "${STAGING_DIR}"
  fi
  if [[ "${CLEANUP_OUTPUT_DIR}" == "true" && -d "${OUTPUT_DIR}" ]]; then
    rm -rf "${OUTPUT_DIR}"
  fi
  return "${exit_code}"
}
trap cleanup EXIT

# ------------------------------------------------------------------------------
# Active Failure Notification Trap
# ------------------------------------------------------------------------------
on_error() {
  local line_no="$1"
  local failed_command="$2"
  local error_code="$3"

  echo "[-] ERROR: Command '${failed_command}' failed on line ${line_no} with exit code ${error_code}" >&2

  if [[ -n "${DISCORD_WEBHOOK_URL}" ]]; then
    local payload
    payload=$(cat <<EOF
{
  "embeds": [{
    "title": "🚨 Backup Failed: ${SERVICE_NAME}",
    "color": 15158332,
    "fields": [
      { "name": "Host", "value": "$(hostname)", "inline": true },
      { "name": "Mode", "value": "${BACKUP_MODE}", "inline": true },
      { "name": "Exit Code", "value": "${error_code}", "inline": true },
      { "name": "Line", "value": "${line_no}", "inline": true },
      { "name": "Failed Command", "value": "\`${failed_command}\`", "inline": false },
      { "name": "Timestamp", "value": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')", "inline": false }
    ]
  }]
}
EOF
    )
    curl -fsS -H "Content-Type: application/json" -d "${payload}" "${DISCORD_WEBHOOK_URL}" || true
  fi
}
trap 'on_error "${LINENO}" "${BASH_COMMAND}" "$?"' ERR

# ------------------------------------------------------------------------------
# Remote Backup Retention & Pruning Function
# ------------------------------------------------------------------------------
# shellcheck disable=SC2120
prune_remote_backups() {
  local target_dest="${1:-}"

  echo "[+] Initiating remote backup pruning (retention policy: ${BACKUP_RETENTION_DAYS} days)..."

  # 1. Enforce safety latch: must run strictly AFTER upload verification succeeds
  if [[ "${BACKUP_UPLOAD_VERIFIED:-false}" != "true" ]]; then
    echo "[-] SAFETY ABORT: prune_remote_backups() refused to execute: new backup upload has not been verified." >&2
    exit 1
  fi

  # 2. Determine target remote destination
  if [[ -z "${target_dest}" ]]; then
    if [[ -n "${B2_DEST_PATH:-}" ]]; then
      target_dest="${B2_DEST_PATH}"
    elif [[ -n "${BACKUP_DEST_BUCKET:-}" ]]; then
      local dest_prefix="${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME}}"
      dest_prefix="${dest_prefix#/}"
      dest_prefix="${dest_prefix%/}"
      target_dest=":s3:${BACKUP_DEST_BUCKET}/${dest_prefix}"
    else
      echo "[!] Pruning skipped: No remote destination configured (neither B2_DEST_PATH nor BACKUP_DEST_BUCKET is set)."
      return 0
    fi
  fi

  if ! command -v rclone >/dev/null 2>&1; then
    echo "[-] WARNING: rclone not found in PATH. Skipping remote backup pruning." >&2
    return 0
  fi

  # 3. Assemble rclone authentication / endpoint arguments
  local rclone_args=()
  local cleanup_target="${target_dest}"

  if [[ "${target_dest}" == :s3:* ]]; then
    rclone_args+=("--s3-provider=Other" "--s3-no-check-bucket")
    local endpoint="${BACKUP_DEST_ENDPOINT:-}"
    if [[ -n "${endpoint}" ]]; then
      if [[ "${endpoint}" != http* ]]; then
        endpoint="https://${endpoint}"
      fi
      rclone_args+=("--s3-endpoint=${endpoint}")
    fi
    if [[ -n "${BACKUP_DEST_ACCESS_KEY_ID:-}" ]]; then
      rclone_args+=("--s3-access-key-id=${BACKUP_DEST_ACCESS_KEY_ID}")
    fi
    if [[ -n "${BACKUP_DEST_SECRET_ACCESS_KEY:-}" ]]; then
      rclone_args+=("--s3-secret-access-key=${BACKUP_DEST_SECRET_ACCESS_KEY}")
    fi
    cleanup_target=":s3:${BACKUP_DEST_BUCKET}"
  fi

  local min_age_arg="${BACKUP_RETENTION_DAYS}d"

  # 4. Discover and log candidates older than BACKUP_RETENTION_DAYS
  echo "[+] Scanning ${target_dest} for archives older than ${BACKUP_RETENTION_DAYS} days..."
  local candidate_list
  candidate_list=$(rclone lsl "${target_dest}" "${rclone_args[@]}" --min-age "${min_age_arg}" 2>/dev/null || true)

  if [[ -z "${candidate_list//[[:space:]]/}" ]]; then
    echo "[+] No remote archives older than ${BACKUP_RETENTION_DAYS} day(s) found in ${target_dest}. Nothing to prune."
  else
    local candidate_count
    candidate_count=$(echo "${candidate_list}" | grep -c . || true)
    echo "[+] Discovered ${candidate_count} remote archive(s) eligible for pruning in ${target_dest}:"
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      echo "    - ${line}"
    done <<< "${candidate_list}"

    # 5. Execute pruning (or simulate if DRY_RUN)
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[*] DRY_RUN is true: Simulating deletion with --dry-run (no remote files will be deleted)..."
      rclone delete "${target_dest}" "${rclone_args[@]}" --min-age "${min_age_arg}" --dry-run
      echo "[+] DRY_RUN simulation completed successfully. The above candidate(s) would be pruned."
    else
      echo "[+] Deleting archives older than ${BACKUP_RETENTION_DAYS} day(s)..."
      rclone delete "${target_dest}" "${rclone_args[@]}" --min-age "${min_age_arg}"
      echo "[+] Pruning completed successfully. Pruned archive(s) with timestamp and size:"
      while IFS= read -r line; do
        [[ -z "${line}" ]] && continue
        echo "    [PRUNED] ${line}"
      done <<< "${candidate_list}"
    fi
  fi

  # 6. Call rclone cleanup if supported
  echo "[+] Invoking rclone cleanup on ${cleanup_target}..."
  local cleanup_opts=("${rclone_args[@]}")
  if [[ "${DRY_RUN}" == "true" ]]; then
    cleanup_opts+=("--dry-run")
  fi
  if rclone cleanup "${cleanup_target}" "${cleanup_opts[@]}" 2>/dev/null; then
    echo "[+] Remote cleanup completed successfully on ${cleanup_target}."
  else
    echo "[*] Remote cleanup completed (or not supported on remote backend; non-fatal)."
  fi

  return 0
}

if [[ "${PRUNE_ONLY}" == "true" ]]; then
  prune_remote_backups
  exit 0
fi

# ------------------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------------------
if [[ -z "${BACKUP_PASSPHRASE}" ]]; then
  echo "[-] FATAL: Neither BACKUP_PASSPHRASE nor BACKUP_ENCRYPTION_KEY is set. Aborting backup." >&2
  exit 1
fi

mkdir -p "${STAGING_DIR}" "${OUTPUT_DIR}"

echo "[+] Starting ${SERVICE_NAME} backup (${TIMESTAMP}) with mode '${BACKUP_MODE}'..."

# ------------------------------------------------------------------------------
# Strategy Execution
# ------------------------------------------------------------------------------
case "${BACKUP_MODE}" in
  sqlite-auto)
    if [[ ! -d "${BACKUP_SOURCE_DIR}" ]]; then
      echo "[-] FATAL: Source directory ${BACKUP_SOURCE_DIR} does not exist. Aborting." >&2
      exit 1
    fi
    BACKUP_SOURCE_DIR="$(cd "${BACKUP_SOURCE_DIR}" && pwd)"

    echo "[+] Scanning ${BACKUP_SOURCE_DIR} for SQLite databases and assets..."

    # Replicate directory hierarchy
    while IFS= read -r -d '' dir; do
      rel_dir="${dir#./}"
      if [[ -n "${rel_dir}" && "${rel_dir}" != "." ]]; then
        mkdir -p "${STAGING_DIR}/${rel_dir}"
      fi
    done < <(cd "${BACKUP_SOURCE_DIR}" && find . -type d -print0)

    # Scan and process files
    local_db_count=0
    local_asset_count=0
    local_skip_count=0

    while IFS= read -r -d '' file; do
      rel_path="${file#./}"
      dest_path="${STAGING_DIR}/${rel_path}"
      dest_dir="$(dirname "${dest_path}")"
      mkdir -p "${dest_dir}"

      case "${rel_path}" in
        *-wal|*-shm|*-journal)
          # Transient SQLite journal files: ignore to avoid corruption
          local_skip_count=$((local_skip_count + 1))
          ;;
        *.sqlite|*.sqlite3|*.db)
          echo "[+] Snapshotting SQLite DB: ${rel_path} -> ${dest_path}"
          sqlite3 "${BACKUP_SOURCE_DIR}/${rel_path}" ".backup '${dest_path}'"
          local_db_count=$((local_db_count + 1))
          ;;
        *)
          echo "[+] Copying non-database asset: ${rel_path}"
          cp -p "${BACKUP_SOURCE_DIR}/${rel_path}" "${dest_path}"
          local_asset_count=$((local_asset_count + 1))
          ;;
      esac
    done < <(cd "${BACKUP_SOURCE_DIR}" && find . \( -type f -o -type l \) -print0)

    echo "[+] sqlite-auto scan completed: ${local_db_count} database(s) snapshotted, ${local_asset_count} asset(s) copied, ${local_skip_count} journal file(s) ignored."
    ;;

  filesystem)
    if [[ ! -d "${BACKUP_SOURCE_DIR}" ]]; then
      echo "[-] FATAL: Source directory ${BACKUP_SOURCE_DIR} does not exist. Aborting." >&2
      exit 1
    fi
    BACKUP_SOURCE_DIR="$(cd "${BACKUP_SOURCE_DIR}" && pwd)"

    echo "[+] Recursively copying directory tree from ${BACKUP_SOURCE_DIR} to staging..."
    cp -a "${BACKUP_SOURCE_DIR}/." "${STAGING_DIR}/"
    echo "[+] Filesystem staging completed."
    ;;

  hook)
    echo "[+] Executing pre-backup hook script: ${PRE_BACKUP_SCRIPT}..."
    if [[ ! -f "${PRE_BACKUP_SCRIPT}" ]]; then
      echo "[-] FATAL: Pre-backup hook script '${PRE_BACKUP_SCRIPT}' not found. Aborting." >&2
      exit 1
    fi

    if [[ -x "${PRE_BACKUP_SCRIPT}" ]]; then
      "${PRE_BACKUP_SCRIPT}" "${STAGING_DIR}" "${BACKUP_SOURCE_DIR:-}"
    else
      echo "[*] Hook script is not executable, invoking with /bin/bash..."
      /bin/bash "${PRE_BACKUP_SCRIPT}" "${STAGING_DIR}" "${BACKUP_SOURCE_DIR:-}"
    fi
    echo "[+] Pre-backup hook completed successfully."
    ;;

  *)
    echo "[-] FATAL: Unsupported BACKUP_MODE='${BACKUP_MODE}'. Valid modes: sqlite-auto, filesystem, hook." >&2
    exit 1
    ;;
esac

# ------------------------------------------------------------------------------
# Package and Encrypt Archive (Standard OpenSSL AES-256-CBC PBKDF2)
# ------------------------------------------------------------------------------
ARCHIVE_FILENAME="${SERVICE_NAME}-backup-${TIMESTAMP}.tar.gz.enc"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_FILENAME}"

echo "[+] Packaging and encrypting archive with OpenSSL AES-256-CBC (PBKDF2, 100,000 iterations, SHA256)..."
export BACKUP_PASSPHRASE
tar -cz -C "${STAGING_DIR}" . | \
  openssl enc -aes-256-cbc -md sha256 -pbkdf2 -iter 100000 -salt \
  -pass env:BACKUP_PASSPHRASE \
  -out "${ARCHIVE_PATH}"

ARCHIVE_SIZE=$(wc -c < "${ARCHIVE_PATH}" | tr -d ' ')
echo "[+] Encrypted archive created successfully: ${ARCHIVE_FILENAME} (${ARCHIVE_SIZE} bytes)"

# ------------------------------------------------------------------------------
# Cloud Rotation / Upload (B2 / S3 via rclone or aws-cli)
# ------------------------------------------------------------------------------
if [[ -n "${B2_DEST_PATH:-}" || ( -n "${BACKUP_DEST_BUCKET:-}" && -n "${BACKUP_DEST_ACCESS_KEY_ID:-}" ) ]]; then
  endpoint="${BACKUP_DEST_ENDPOINT:-}"
  if [[ -n "${endpoint}" && "${endpoint}" != http* ]]; then
    endpoint="https://${endpoint}"
  fi

  if [[ -n "${B2_DEST_PATH:-}" ]]; then
    upload_target="${B2_DEST_PATH}/${ARCHIVE_FILENAME}"
    verify_target="${B2_DEST_PATH}/${ARCHIVE_FILENAME}"
    rclone_upload_args=()
    if [[ "${B2_DEST_PATH}" == :s3:* ]]; then
      rclone_upload_args+=(
        "--s3-provider=Other"
        "--s3-no-check-bucket"
      )
      if [[ -n "${endpoint}" ]]; then
        rclone_upload_args+=("--s3-endpoint=${endpoint}")
      fi
      if [[ -n "${BACKUP_DEST_ACCESS_KEY_ID:-}" ]]; then
        rclone_upload_args+=("--s3-access-key-id=${BACKUP_DEST_ACCESS_KEY_ID}")
      fi
      if [[ -n "${BACKUP_DEST_SECRET_ACCESS_KEY:-}" ]]; then
        rclone_upload_args+=("--s3-secret-access-key=${BACKUP_DEST_SECRET_ACCESS_KEY}")
      fi
    fi
  else
    dest_prefix="${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME}}"
    dest_prefix="${dest_prefix#/}"
    dest_prefix="${dest_prefix%/}"
    s3_dest_path="${dest_prefix}/${ARCHIVE_FILENAME}"
    upload_target=":s3:${BACKUP_DEST_BUCKET}/${s3_dest_path}"
    verify_target=":s3:${BACKUP_DEST_BUCKET}/${s3_dest_path}"
    rclone_upload_args=(
      "--s3-provider=Other"
      "--s3-no-check-bucket"
    )
    if [[ -n "${endpoint}" ]]; then
      rclone_upload_args+=("--s3-endpoint=${endpoint}")
    fi
    if [[ -n "${BACKUP_DEST_ACCESS_KEY_ID:-}" ]]; then
      rclone_upload_args+=("--s3-access-key-id=${BACKUP_DEST_ACCESS_KEY_ID}")
    fi
    if [[ -n "${BACKUP_DEST_SECRET_ACCESS_KEY:-}" ]]; then
      rclone_upload_args+=("--s3-secret-access-key=${BACKUP_DEST_SECRET_ACCESS_KEY}")
    fi
  fi

  echo "[+] Uploading ${ARCHIVE_FILENAME} to ${upload_target}..."

  if command -v rclone >/dev/null 2>&1; then
    rclone copyto "${ARCHIVE_PATH}" "${upload_target}" "${rclone_upload_args[@]}"

    # Verify upload
    echo "[+] Verifying cloud upload of ${ARCHIVE_FILENAME}..."
    remote_check=$(rclone lsf "${verify_target}" "${rclone_upload_args[@]}" 2>/dev/null || true)
    if [[ -z "${remote_check}" ]]; then
      echo "[-] FATAL: Upload verification failed: ${ARCHIVE_FILENAME} not found on remote after upload." >&2
      exit 1
    fi
    BACKUP_UPLOAD_VERIFIED=true
    echo "[+] Cloud upload verified successfully: ${verify_target}"

  elif command -v aws >/dev/null 2>&1; then
    AWS_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID}" \
    AWS_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
    aws s3 cp "${ARCHIVE_PATH}" \
      "s3://${BACKUP_DEST_BUCKET}/${s3_dest_path}" \
      ${endpoint:+--endpoint-url "${endpoint}"}

    # Verify upload
    echo "[+] Verifying cloud upload of ${ARCHIVE_FILENAME}..."
    remote_check=$(AWS_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID}" \
      AWS_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
      aws s3 ls "s3://${BACKUP_DEST_BUCKET}/${s3_dest_path}" \
      ${endpoint:+--endpoint-url "${endpoint}"} 2>/dev/null || true)
    if [[ -z "${remote_check}" ]]; then
      echo "[-] FATAL: Upload verification failed: ${ARCHIVE_FILENAME} not found on remote after upload." >&2
      exit 1
    fi
    BACKUP_UPLOAD_VERIFIED=true
    echo "[+] Cloud upload verified successfully: s3://${BACKUP_DEST_BUCKET}/${s3_dest_path}"
  else
    echo "[-] Error: Neither rclone nor aws-cli found in PATH. Skipping cloud upload." >&2
    exit 1
  fi
  echo "[+] Cloud upload completed successfully."

  # Prune remote backups strictly AFTER new backup creation and upload verification have succeeded
  prune_remote_backups
else
  echo "[!] Cloud upload skipped (destination bucket or credentials not configured)."
fi

# ------------------------------------------------------------------------------
# Dead Man's Snitch / Healthchecks.io Ping
# ------------------------------------------------------------------------------
if [[ -n "${HEALTHCHECK_PING_URL:-}" ]]; then
  echo "[+] Pinging Dead Man's Snitch (${HEALTHCHECK_PING_URL})..."
  curl -fsS -m 10 --retry 3 "${HEALTHCHECK_PING_URL}" >/dev/null || true
fi

echo "[+] Backup completed successfully for ${SERVICE_NAME}!"
