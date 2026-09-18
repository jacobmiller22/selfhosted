#!/usr/bin/env bash
# ==============================================================================
# Container Entrypoint for Standardized Backup Runner
# ==============================================================================

set -euo pipefail

# Fallback: Support BACKUP_ENCRYPTION_KEY if BACKUP_PASSPHRASE is not set
BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-${BACKUP_ENCRYPTION_KEY:-}}"

# Save environment for cron executions (cron starts with a stripped environment)
mkdir -p /run/secrets
cat <<EOF > /run/secrets/env_vars
export SERVICE_NAME="${SERVICE_NAME:-actual}"
export BACKUP_SOURCE_DIR="${BACKUP_SOURCE_DIR:-/tmp/actual-data}"
export BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE}"
export BACKUP_DEST_ENDPOINT="${BACKUP_DEST_ENDPOINT:-}"
export BACKUP_DEST_BUCKET="${BACKUP_DEST_BUCKET:-}"
export BACKUP_DEST_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID:-}"
export BACKUP_DEST_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY:-}"
export BACKUP_DEST_PREFIX="${BACKUP_DEST_PREFIX:-backups/actual}"
export DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
export HEALTHCHECK_PING_URL="${HEALTHCHECK_PING_URL:-}"
EOF
chmod 600 /run/secrets/env_vars

CRON_SCHEDULE="${CRON_SCHEDULE:-0 16 * * *}"
mkdir -p /etc/crontabs
echo "${CRON_SCHEDULE} /bin/bash /app/backup.sh >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
chmod 600 /etc/crontabs/root

echo "[+] Standardized Backup Runner initialized"
echo "[+] Service: ${SERVICE_NAME:-actual}"
echo "[+] Cron Schedule: ${CRON_SCHEDULE}"

if [[ "${BACKUP_ON_STARTUP:-false}" == "true" ]]; then
  echo "[+] Running initial backup on startup..."
  /bin/bash /app/backup.sh || echo "[-] Warning: Initial backup failed, continuing to cron scheduler." >&2
fi

echo "[+] Starting crond in foreground..."
exec crond -f -l 2
