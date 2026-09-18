#!/usr/bin/env bash
# ==============================================================================
# Actual Budget Standardized Backup Runner
# ==============================================================================
# - Strict shell error handling (set -euo pipefail)
# - Online SQLite snapshotting (avoids corruption via sqlite3 .backup)
# - Standardized OpenSSL AES-256-CBC PBKDF2 encryption (100k iterations)
# - Non-destructive ISO timestamped filenames (e.g. actual-backup-YYYY-MM-DD_HH-MM-SS.tar.gz.enc)
# - Cloud upload via rclone / aws-cli with S3 & B2 compatibility
# - Failure alerting via Discord webhook traps
# - Success ping via Healthchecks.io / Dead Man's Snitch
# ==============================================================================

set -euo pipefail

# Source environment variables if running inside cron
if [[ -f /run/secrets/env_vars ]]; then
  # shellcheck source=/dev/null
  source /run/secrets/env_vars
fi

SERVICE_NAME="${SERVICE_NAME:-actual}"
BACKUP_SOURCE_DIR="${BACKUP_SOURCE_DIR:-/tmp/actual-data}"
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

BACKUP_DEST_ENDPOINT="${BACKUP_DEST_ENDPOINT:-}"
BACKUP_DEST_BUCKET="${BACKUP_DEST_BUCKET:-}"
BACKUP_DEST_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID:-}"
BACKUP_DEST_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY:-}"
BACKUP_DEST_PREFIX="${BACKUP_DEST_PREFIX:-backups/actual}"

cleanup() {
  local exit_code=$?
  rm -rf "${STAGING_DIR}"
  if [[ "${CLEANUP_OUTPUT_DIR}" == "true" ]]; then
    rm -rf "${OUTPUT_DIR}"
  fi
  exit "${exit_code}"
}
trap cleanup EXIT

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

if [[ -z "${BACKUP_PASSPHRASE}" ]]; then
  echo "[-] FATAL: Neither BACKUP_PASSPHRASE nor BACKUP_ENCRYPTION_KEY is set. Aborting backup." >&2
  exit 1
fi

if [[ ! -d "${BACKUP_SOURCE_DIR}" ]]; then
  echo "[-] FATAL: Source directory ${BACKUP_SOURCE_DIR} does not exist. Aborting." >&2
  exit 1
fi

mkdir -p "${STAGING_DIR}" "${OUTPUT_DIR}"
echo "[+] Starting Actual Budget backup (${TIMESTAMP})..."

# ------------------------------------------------------------------------------
# 1. Snapshot Live SQLite Databases & Sync Blobs
# ------------------------------------------------------------------------------

# Snapshot server-files/account.sqlite using SQLite Online Backup API
if [[ -f "${BACKUP_SOURCE_DIR}/server-files/account.sqlite" ]]; then
  mkdir -p "${STAGING_DIR}/server-files"
  echo "[+] Snapshotting SQLite DB: server-files/account.sqlite"
  sqlite3 "${BACKUP_SOURCE_DIR}/server-files/account.sqlite" ".backup '${STAGING_DIR}/server-files/account.sqlite'"
elif [[ -d "${BACKUP_SOURCE_DIR}/server-files" ]]; then
  echo "[-] Warning: server-files directory exists but account.sqlite was not found." >&2
fi

# Snapshot user-files/*.sqlite and copy user-files/*.blob
if [[ -d "${BACKUP_SOURCE_DIR}/user-files" ]]; then
  mkdir -p "${STAGING_DIR}/user-files"

  # Find all SQLite DBs in user-files
  shopt -s nullglob
  for db_file in "${BACKUP_SOURCE_DIR}/user-files/"*.sqlite "${BACKUP_SOURCE_DIR}/user-files/"*.sqlite3 "${BACKUP_SOURCE_DIR}/user-files/"*.db; do
    if [[ -f "${db_file}" ]]; then
      base_name="$(basename "${db_file}")"
      echo "[+] Snapshotting SQLite DB: user-files/${base_name}"
      sqlite3 "${db_file}" ".backup '${STAGING_DIR}/user-files/${base_name}'"
    fi
  done

  # Copy client sync blobs
  for blob_file in "${BACKUP_SOURCE_DIR}/user-files/"*.blob; do
    if [[ -f "${blob_file}" ]]; then
      base_name="$(basename "${blob_file}")"
      echo "[+] Copying blob asset: user-files/${base_name}"
      cp "${blob_file}" "${STAGING_DIR}/user-files/${base_name}"
    fi
  done
  shopt -u nullglob
fi

# Copy metadata file (.migrate) if present
if [[ -f "${BACKUP_SOURCE_DIR}/.migrate" ]]; then
  cp "${BACKUP_SOURCE_DIR}/.migrate" "${STAGING_DIR}/.migrate"
fi

# ------------------------------------------------------------------------------
# 2. Package and Encrypt with Standard OpenSSL
# ------------------------------------------------------------------------------
ARCHIVE_FILENAME="${SERVICE_NAME}-backup-${TIMESTAMP}.tar.gz.enc"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_FILENAME}"

echo "[+] Packaging and encrypting archive with OpenSSL AES-256-CBC (PBKDF2, 100,000 iterations)..."
export BACKUP_PASSPHRASE
tar -cz -C "${STAGING_DIR}" . | \
  openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
  -pass env:BACKUP_PASSPHRASE \
  -out "${ARCHIVE_PATH}"

ARCHIVE_SIZE=$(wc -c < "${ARCHIVE_PATH}" | tr -d ' ')
echo "[+] Encrypted archive created successfully: ${ARCHIVE_FILENAME} (${ARCHIVE_SIZE} bytes)"

# ------------------------------------------------------------------------------
# 3. Cloud Upload (B2 / S3 via rclone or aws-cli)
# ------------------------------------------------------------------------------
if [[ -n "${BACKUP_DEST_BUCKET:-}" && -n "${BACKUP_DEST_ACCESS_KEY_ID:-}" ]]; then
  dest_prefix="${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME}}"
  dest_prefix="${dest_prefix#/}"
  dest_prefix="${dest_prefix%/}"
  s3_dest_path="${dest_prefix}/${ARCHIVE_FILENAME}"

  endpoint="${BACKUP_DEST_ENDPOINT:-}"
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
      --s3-secret-access-key="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
      --s3-no-check-bucket
  elif command -v aws >/dev/null 2>&1; then
    AWS_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID}" \
    AWS_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY}" \
    aws s3 cp "${ARCHIVE_PATH}" \
      "s3://${BACKUP_DEST_BUCKET}/${s3_dest_path}" \
      ${endpoint:+--endpoint-url "${endpoint}"}
  else
    echo "[-] Error: Neither rclone nor aws-cli found in PATH. Skipping cloud upload." >&2
    exit 1
  fi
  echo "[+] Cloud upload completed successfully."
else
  echo "[!] Cloud upload skipped (destination bucket or credentials not configured)."
fi

# ------------------------------------------------------------------------------
# 4. Dead Man's Snitch / Healthchecks.io Ping
# ------------------------------------------------------------------------------
if [[ -n "${HEALTHCHECK_PING_URL:-}" ]]; then
  echo "[+] Pinging Dead Man's Snitch (${HEALTHCHECK_PING_URL})..."
  curl -fsS -m 10 --retry 3 "${HEALTHCHECK_PING_URL}" >/dev/null || true
fi

echo "[+] Actual Budget backup completed successfully!"
