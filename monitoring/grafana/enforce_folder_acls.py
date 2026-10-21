#!/usr/bin/env python3
"""
Enforce default-deny folder permissions on Grafana SQLite database.
- Strips global Viewer permission (dashboard_id = -1) so non-admin Viewers have no default access.
- Restricts 'Infrastructure' and 'Financial Intelligence' folders to Editor and Admin only.
- Explicitly grants 'Viewer' read permission (permission = 1) to 'BTC Up/Down' folder.
"""

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path


def enforce_acls(db_path: Path) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Grafana database not found at {db_path}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Ensure default-deny: remove global Viewer permission (dashboard_id = -1)
        cur.execute(
            "DELETE FROM dashboard_acl WHERE dashboard_id = -1 AND role = 'Viewer'"
        )
        global_viewers_removed = cur.rowcount

        # 2. Look up folders by uid or title (case-insensitive)
        cur.execute(
            "SELECT id, uid, title FROM dashboard WHERE is_folder = 1"
        )
        folders = {}
        for row in cur.fetchall():
            folders[row[1].lower()] = {"id": row[0], "title": row[2]}
            folders[row[2].lower()] = {"id": row[0], "title": row[2]}

        results = {
            "global_viewers_removed": global_viewers_removed,
            "folders_configured": {},
        }

        # 3. For each folder, configure explicit permissions
        # Mapping: folder identifier (uid or title) -> list of (role, permission)
        folder_policy = {
            "infrastructure": [("Editor", 2), ("Admin", 4)],
            "infrastructure-alerts": [("Editor", 2), ("Admin", 4)],
            "financial-intelligence": [("Editor", 2), ("Admin", 4)],
            "btcupdown": [("Viewer", 1), ("Editor", 2), ("Admin", 4)],
        }

        for folder_key, allowed_roles in folder_policy.items():
            folder_info = folders.get(folder_key.lower())
            if not folder_info:
                # Folder might not be imported yet if Grafana hasn't booted
                continue

            folder_id = folder_info["id"]

            # Clear existing ACLs for this folder
            cur.execute("DELETE FROM dashboard_acl WHERE dashboard_id = ?", (folder_id,))

            # Insert explicit ACLs
            for role, perm in allowed_roles:
                cur.execute(
                    """
                    INSERT INTO dashboard_acl (org_id, dashboard_id, permission, role, created, updated)
                    VALUES (1, ?, ?, ?, ?, ?)
                    """,
                    (folder_id, perm, role, now, now),
                )

            results["folders_configured"][folder_key] = [r[0] for r in allowed_roles]

        conn.commit()
        return results
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Enforce default-deny folder permissions in Grafana.")
    parser.add_argument("--db", type=Path, default=Path("/var/lib/grafana/grafana.db"), help="Path to grafana.db")
    args = parser.parse_args()

    results = enforce_acls(args.db)
    print(f"ACL enforcement complete: {results}")


if __name__ == "__main__":
    main()
