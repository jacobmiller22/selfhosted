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

        # 2. Mark folders as having custom ACLs; child dashboards inherit from parent folder
        cur.execute("UPDATE dashboard SET has_acl = 1 WHERE is_folder = 1")
        cur.execute("UPDATE dashboard SET has_acl = 0 WHERE is_folder = 0")

        # 3. Look up folders by uid or title (case-insensitive)
        cur.execute(
            "SELECT id, uid, title FROM dashboard WHERE is_folder = 1"
        )
        folders = {}
        for row in cur.fetchall():
            folder_record = {"id": row[0], "uid": row[1], "title": row[2]}
            folders[row[1].lower()] = folder_record
            folders[row[2].lower()] = folder_record

        results = {
            "global_viewers_removed": global_viewers_removed,
            "folders_configured": {},
            "viewer_rbac_permissions_pruned": 0,
        }

        # 4. For each folder, configure explicit permissions in dashboard_acl
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

        # 5. Enforce modern Grafana 11 RBAC permission table if present
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='permission'")
        if cur.fetchone():
            viewer_role_id = None
            cur.execute("SELECT id FROM role WHERE name = 'managed:builtins:viewer:permissions'")
            r_row = cur.fetchone()
            if r_row:
                viewer_role_id = r_row[0]
            else:
                cur.execute("SELECT id FROM builtin_role WHERE name = 'Viewer'")
                b_row = cur.fetchone()
                if b_row:
                    viewer_role_id = b_row[0]

            if viewer_role_id is not None:
                allowed_folder_uids = []
                for f_key, allowed_roles in folder_policy.items():
                    if any(r[0] == "Viewer" for r in allowed_roles):
                        f_info = folders.get(f_key.lower())
                        if f_info and f_info.get("uid"):
                            allowed_folder_uids.append(f_info["uid"])

                allowed_folder_scopes = [f"folders:uid:{uid}" for uid in allowed_folder_uids]
                if allowed_folder_scopes:
                    placeholders = ",".join("?" * len(allowed_folder_scopes))
                    cur.execute(
                        f"""
                        DELETE FROM permission
                        WHERE role_id = ?
                          AND (
                            (scope LIKE 'folders:uid:%' AND scope NOT IN ({placeholders}))
                            OR scope IN ('datasources:uid:actual-sqlite', 'datasources:uid:victoriametrics')
                          )
                        """,
                        [viewer_role_id] + allowed_folder_scopes,
                    )
                else:
                    cur.execute(
                        """
                        DELETE FROM permission
                        WHERE role_id = ?
                          AND (
                            scope LIKE 'folders:uid:%'
                            OR scope IN ('datasources:uid:actual-sqlite', 'datasources:uid:victoriametrics')
                          )
                        """,
                        (viewer_role_id,),
                    )
                results["viewer_rbac_permissions_pruned"] = cur.rowcount

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
