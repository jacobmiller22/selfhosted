#!/usr/bin/env bash
# ==============================================================================
# Canonical Entrypoint for Reusable Backup Runner
# ==============================================================================
# Handles:
# 1. Dynamic secret export to /run/secrets/env_vars for cron execution
# 2. Dynamic crontab configuration via CRON_SCHEDULE
# 3. Startup backup hook via BACKUP_ON_STARTUP=true
# 4. Signal trapping (SIGTERM, SIGINT) for graceful shutdown
# ==============================================================================

set -euo pipefail

# Fallback: Support BACKUP_ENCRYPTION_KEY if BACKUP_PASSPHRASE is not set
BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-${BACKUP_ENCRYPTION_KEY:-}}"

# If arguments were passed to entrypoint, execute them directly
if [[ $# -gt 0 ]]; then
  exec "$@"
fi

# ------------------------------------------------------------------------------
# 1. Dynamic Secret Export for Cron Execution
# ------------------------------------------------------------------------------
# Crond runs with a sanitized, minimal environment.
# Export container variables into a secured secrets file for backup-engine.sh.
mkdir -p /run/secrets
chmod 700 /run/secrets

{
  printf 'export SERVICE_NAME=%q\n' "${SERVICE_NAME:-unknown-service}"
  printf 'export BACKUP_MODE=%q\n' "${BACKUP_MODE:-sqlite-auto}"
  printf 'export BACKUP_SOURCE_DIR=%q\n' "${BACKUP_SOURCE_DIR:-/data}"
  printf 'export BACKUP_PASSPHRASE=%q\n' "${BACKUP_PASSPHRASE}"
  printf 'export PRE_BACKUP_SCRIPT=%q\n' "${PRE_BACKUP_SCRIPT:-/hooks/pre-backup.sh}"
  printf 'export BACKUP_DEST_ENDPOINT=%q\n' "${BACKUP_DEST_ENDPOINT:-}"
  printf 'export BACKUP_DEST_BUCKET=%q\n' "${BACKUP_DEST_BUCKET:-}"
  printf 'export BACKUP_DEST_ACCESS_KEY_ID=%q\n' "${BACKUP_DEST_ACCESS_KEY_ID:-}"
  printf 'export BACKUP_DEST_SECRET_ACCESS_KEY=%q\n' "${BACKUP_DEST_SECRET_ACCESS_KEY:-}"
  printf 'export BACKUP_DEST_PREFIX=%q\n' "${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME:-unknown-service}}"
  printf 'export DISCORD_WEBHOOK_URL=%q\n' "${DISCORD_WEBHOOK_URL:-}"
  printf 'export HEALTHCHECK_PING_URL=%q\n' "${HEALTHCHECK_PING_URL:-}"
  printf 'export OUTPUT_DIR=%q\n' "${OUTPUT_DIR:-}"
  printf 'export PATH=%q\n' "${PATH}"
} > /run/secrets/env_vars
chmod 600 /run/secrets/env_vars

# ------------------------------------------------------------------------------
# 2. Dynamic Crontab Configuration
# ------------------------------------------------------------------------------
CRON_SCHEDULE="${CRON_SCHEDULE:-0 16 * * *}"
mkdir -p /etc/crontabs
echo "${CRON_SCHEDULE} /bin/bash /app/backup-engine.sh >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
chmod 600 /etc/crontabs/root

echo "[+] Reusable Backup Runner initialized"
echo "[+] Service: ${SERVICE_NAME:-unknown-service}"
echo "[+] Mode: ${BACKUP_MODE:-sqlite-auto}"
echo "[+] Source: ${BACKUP_SOURCE_DIR:-/data}"
echo "[+] Cron Schedule: ${CRON_SCHEDULE}"

# ------------------------------------------------------------------------------
# 3. Optional Startup Backup Execution
# ------------------------------------------------------------------------------
if [[ "${BACKUP_ON_STARTUP:-false}" == "true" ]]; then
  echo "[+] BACKUP_ON_STARTUP is true: running initial backup now..."
  /bin/bash /app/backup-engine.sh || echo "[-] Warning: Initial startup backup failed; continuing to cron daemon." >&2
fi

# ------------------------------------------------------------------------------
# 4. Graceful Signal Handling & Daemon Execution
# ------------------------------------------------------------------------------
cleanup_and_exit() {
  echo "[+] Shutdown signal received, stopping crond gracefully..."
  if [[ -n "${CROND_PID:-}" ]]; then
    kill -TERM "${CROND_PID}" 2>/dev/null || true
    wait "${CROND_PID}" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup_and_exit SIGTERM SIGINT

echo "[+] Starting crond daemon..."
crond -f -l 2 &
CROND_PID=$!
wait "${CROND_PID}"
