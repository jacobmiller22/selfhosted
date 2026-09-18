#!/usr/bin/env bash
# ==============================================================================
# Universal Self-Hosted Backup Runner Template
# ==============================================================================
# Features:
# - Strict error handling (set -euo pipefail)
# - Online SQLite snapshotting (avoids live corruption via sqlite3 .backup)
# - OpenSSL AES-256-CBC PBKDF2 encryption (zero-dependency recovery)
# - Non-destructive ISO timestamped filenames
# - Active failure trapping with Discord webhook embeds
# - Passive Dead Man's Snitch ping (Healthchecks.io) on success
# - Automatic staging cleanup via EXIT trap
# ==============================================================================

set -euo pipefail

# Source environment variables if running inside cron
if [[ -f /run/secrets/env_vars ]]; then
  # shellcheck source=/dev/null
  source /run/secrets/env_vars
fi

# ------------------------------------------------------------------------------
# Configuration & Defaults
# ------------------------------------------------------------------------------
SERVICE_NAME="${SERVICE_NAME:-unknown-service}"
TIMESTAMP="$(date +'%Y-%m-%d_%H-%M-%S')"
STAGING_DIR="/tmp/backup-staging-${SERVICE_NAME}-${TIMESTAMP}"
CLEANUP_OUTPUT_DIR=false
if [[ -z "${OUTPUT_DIR:-}" ]]; then
  OUTPUT_DIR="/tmp/backup-output-${SERVICE_NAME}-${TIMESTAMP}"
  CLEANUP_OUTPUT_DIR=true
fi

BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-${BACKUP_ENCRYPTION_KEY:-}}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
HEALTHCHECK_PING_URL="${HEALTHCHECK_PING_URL:-}"

BACKUP_DEST_BUCKET="${BACKUP_DEST_BUCKET:-}"
BACKUP_DEST_ENDPOINT="${BACKUP_DEST_ENDPOINT:-}"
BACKUP_DEST_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID:-}"
BACKUP_DEST_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY:-}"
BACKUP_DEST_PREFIX="${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME}}"

# ------------------------------------------------------------------------------
# Cleanup Handler
# ------------------------------------------------------------------------------
cleanup() {
  local exit_code=$?
  rm -rf "${STAGING_DIR}"
  if [[ "${CLEANUP_OUTPUT_DIR}" == "true" ]]; then
    rm -rf "${OUTPUT_DIR}"
  fi
  exit "${exit_code}"
}
trap cleanup EXIT

# ------------------------------------------------------------------------------
# Failure Notification Trap
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
# Validation
# ------------------------------------------------------------------------------
if [[ -z "${BACKUP_PASSPHRASE}" ]]; then
  echo "[-] FATAL: Neither BACKUP_PASSPHRASE nor BACKUP_ENCRYPTION_KEY is set. Aborting backup." >&2
  exit 1
fi

mkdir -p "${STAGING_DIR}" "${OUTPUT_DIR}"

echo "[+] Starting backup for service: ${SERVICE_NAME} (${TIMESTAMP})"

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------
snapshot_sqlite() {
  local src_db="$1"
  local rel_dest="$2"
  local dest_path="${STAGING_DIR}/${rel_dest}"

  mkdir -p "$(dirname "${dest_path}")"
  if [[ -f "${src_db}" ]]; then
    echo "[+] Snapshotting SQLite DB: ${src_db} -> ${dest_path}"
    sqlite3 "${src_db}" ".backup '${dest_path}'"
  else
    echo "[-] Warning: SQLite DB not found at ${src_db}" >&2
  fi
}

copy_assets() {
  local src_dir="$1"
  local rel_dest="$2"
  local dest_path="${STAGING_DIR}/${rel_dest}"

  if [[ -e "${src_dir}" ]]; then
    mkdir -p "$(dirname "${dest_path}")"
    echo "[+] Copying assets: ${src_dir} -> ${dest_path}"
    cp -r "${src_dir}" "${dest_path}"
  else
    echo "[-] Warning: Asset path not found at ${src_dir}" >&2
  fi
}

# ------------------------------------------------------------------------------
# Encrypt and Package
# ------------------------------------------------------------------------------
ARCHIVE_FILENAME="${SERVICE_NAME}-backup-${TIMESTAMP}.tar.gz.enc"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_FILENAME}"

perform_encryption() {
  echo "[+] Encrypting backup with OpenSSL AES-256-CBC (PBKDF2, 100,000 iterations)..."
  export BACKUP_PASSPHRASE
  tar -cz -C "${STAGING_DIR}" . | \
    openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
    -pass env:BACKUP_PASSPHRASE \
    -out "${ARCHIVE_PATH}"

  local archive_size
  archive_size=$(wc -c < "${ARCHIVE_PATH}" | tr -d ' ')
  echo "[+] Archive encrypted successfully: ${ARCHIVE_FILENAME} (${archive_size} bytes)"
}

# ------------------------------------------------------------------------------
# Cloud Upload (S3/B2)
# ------------------------------------------------------------------------------
upload_to_s3() {
  if [[ -n "${BACKUP_DEST_BUCKET:-}" && -n "${BACKUP_DEST_ACCESS_KEY_ID:-}" ]]; then
    local dest_prefix="${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME}}"
    dest_prefix="${dest_prefix#/}"
    dest_prefix="${dest_prefix%/}"
    local s3_dest_path="${dest_prefix}/${ARCHIVE_FILENAME}"

    local endpoint="${BACKUP_DEST_ENDPOINT:-}"
    if [[ -n "${endpoint}" && "${endpoint}" != http* ]]; then
      endpoint="https://${endpoint}"
    fi

    echo "[+] Uploading ${ARCHIVE_FILENAME} to s3://${BACKUP_DEST_BUCKET}/${s3_dest_path}..."
    
    if command -v rclone >/dev/null 2>&1; then
      rclone copyto "${ARCHIVE_PATH}" \
        ":s3:${BACKUP_DEST_BUCKET}/${s3_dest_path}" \
        --s3-provider=Other \
        --s3-endpoint="${endpoint}" \
        --s3-access-key-id="${BACKUP_DEST_ACCESS_KEY_ID}" \
        --s3-secret-access-key="${BACKUP_DEST_SECRET_ACCESS_KEY}"
    elif command -v aws >/dev/null 2>&1; then
      AWS_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID}" \
      AWS_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
      aws s3 cp "${ARCHIVE_PATH}" \
        "s3://${BACKUP_DEST_BUCKET}/${s3_dest_path}" \
        ${endpoint:+--endpoint-url "${endpoint}"}
    else
      echo "[-] Warning: Neither aws-cli nor rclone found in container. Skipping cloud upload." >&2
    fi
  else
    echo "[+] Cloud upload skipped (destination variables not configured)."
  fi
}

# ------------------------------------------------------------------------------
# Dead Man's Snitch Ping
# ------------------------------------------------------------------------------
ping_healthcheck() {
  if [[ -n "${HEALTHCHECK_PING_URL:-}" ]]; then
    echo "[+] Pinging Dead Man's Snitch (Healthchecks.io)..."
    curl -fsS -m 10 --retry 3 "${HEALTHCHECK_PING_URL}" >/dev/null || true
  fi
}
