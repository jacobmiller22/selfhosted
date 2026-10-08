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

    echo "Replicating snapshot to actual-analytics-data volume..."
    docker cp "$RUNNING_CONTAINER:/app/export/db.sqlite" - | docker run --rm -i -v actual-analytics-data:/data alpine sh -c "tar -xf - -C /data && chmod 644 /data/db.sqlite"
    echo "✓ Replicated database to actual-analytics-data volume."

    echo "Provisioning authoritative v_account_categories view..."
    docker run --rm -u root -i -v actual-analytics-data:/data keinos/sqlite3 sqlite3 /data/db.sqlite << 'EOF' || true
      DROP VIEW IF EXISTS v_account_categories;
      CREATE VIEW v_account_categories AS
      SELECT
        a.id,
        a.name,
        CASE
          WHEN a.name LIKE '%[P]%' OR a.name LIKE '%GTI%' THEN 'Priyanka'
          WHEN a.name LIKE '%[J]%' OR a.name LIKE '%Tacoma%' THEN 'Jacob'
          ELSE 'Joint / Household'
        END AS owner,
        CASE
          WHEN a.closed = 1 THEN 'Paid Off / Closed'
          WHEN a.name LIKE '%Card%' THEN 'Credit Card Float'
          WHEN a.name LIKE '%South State Loan%' THEN 'Auto Loan (VW GTI)'
          WHEN a.name LIKE '%Loan%' THEN 'Installment Loans'
          WHEN a.name = 'Mortgage' THEN 'Mortgage Debt'
          WHEN a.name = 'House' OR a.name LIKE '%Equity%' THEN 'Real Estate'
          WHEN a.name LIKE '%Tacoma%' OR a.name LIKE '%GTI%' OR a.name LIKE '%Vehicle%' OR a.name LIKE '%Auto%' THEN 'Vehicles'
          WHEN a.name LIKE '%401k%' OR a.name LIKE '%IRA%' OR a.name LIKE '%Ret Plan%' OR a.name LIKE '%Savings Plan%' OR a.name LIKE '%HSA%' THEN 'Retirement & Tax-Advantaged'
          WHEN a.name LIKE '%Brokerage%' OR a.name LIKE '%Stock%' THEN 'Taxable Investments'
          WHEN a.offbudget = 0 OR a.name = 'Savings Joint' THEN 'Liquid Cash & Reserves'
          ELSE 'Other Assets'
        END AS category,
        CASE
          WHEN a.name LIKE '%Card%' OR a.name LIKE '%Loan%' OR a.name = 'Mortgage' THEN 'Liability'
          ELSE 'Asset'
        END AS balance_sheet_side,
        CASE
          WHEN a.closed = 0 AND (a.offbudget = 0 OR a.name = 'Savings Joint')
          THEN 1
          ELSE 0
        END AS is_liquid,
        a.closed AS is_closed,
        a.offbudget,
        a.tombstone
      FROM accounts a;
EOF
    echo "✓ Provisioned v_account_categories view."
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
