#!/usr/bin/env bash
# ==============================================================================
# Coolify Pre-Backup Hook
# ==============================================================================
# Dumps the Coolify PostgreSQL database (coolify-db) into the staging directory
# prior to archive packaging and OpenSSL encryption.
#
# Canonical invocation pattern:
#   docker exec coolify-db pg_dump -U coolify -d coolify > /staging/coolify.sql
# ==============================================================================

set -euo pipefail

STAGING_DIR="${1:-/staging}"
mkdir -p "${STAGING_DIR}"

echo "[+] Dumping Coolify PostgreSQL database from container coolify-db..."
docker exec coolify-db pg_dump -U coolify -d coolify > "${STAGING_DIR}/coolify.sql"
echo "[+] Coolify database dump completed successfully: ${STAGING_DIR}/coolify.sql"
