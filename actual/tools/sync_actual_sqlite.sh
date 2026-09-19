#!/usr/bin/env bash
set -euo pipefail

# sync_actual_sqlite.sh: Safely snapshots and replicates the decrypted Actual Budget SQLite database
# to the shared actual-analytics-data volume for Grafana analytics without locking or downtime.

CONTAINER_NAME="${CONTAINER_NAME:-actual-auto-categorizer}"
EXPORT_DIR="${EXPORT_DIR:-/var/lib/docker/volumes/actual-analytics-data/_data}"
DEST_PATH="${EXPORT_DIR}/db.sqlite"

echo "=== Actual Budget SQLite Snapshot & Replication Pipeline ==="

# 1. Check if auto-categorizer container is running
RUNNING_CONTAINER=$(docker ps --filter "name=actual-auto-categorizer" --format "{{.Names}}" | head -n 1)

if [ -n "$RUNNING_CONTAINER" ]; then
    echo "Found running auto-categorizer container: $RUNNING_CONTAINER"
    echo "Triggering snapshot export inside container..."
    docker exec "$RUNNING_CONTAINER" node -e '
      import("./dist/actual.js").then(m => {
        const ok = m.exportDatabaseSnapshot(process.env.ANALYTICS_EXPORT_PATH || "/app/export/db.sqlite");
        if (!ok) process.exit(1);
      }).catch(err => { console.error(err); process.exit(1); });
    '
    echo "✓ Container snapshot export successful."
else
    echo "⚠️ Auto-categorizer container not detected. Checking volume directly..."
fi

# 2. Check if destination file exists and verify permissions
if [ -f "$DEST_PATH" ]; then
    chmod 644 "$DEST_PATH" || true
    FILE_SIZE=$(wc -c < "$DEST_PATH" | tr -d ' ')
    echo "✓ Replicated database available at: $DEST_PATH ($FILE_SIZE bytes, chmod 644)"
else
    echo "Notice: Snapshot file will be populated on first auto-categorizer sync cycle."
fi

echo "=== Sync complete ==="
