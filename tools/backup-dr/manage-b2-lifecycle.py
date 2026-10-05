#!/usr/bin/env python3
"""
manage-b2-lifecycle.py

Backblaze B2 Storage Lifecycle and Retention Management Utility.
Provides:
  - 'status': Audit bucket lifecycle rules, storage consumption, file counts, and version bloat.
  - 'apply': Declaratively apply B2 bucket lifecycle rules (30-day retention, 1-day noncurrent purging).
  - 'prune': Clean up obsolete legacy file versions and prune runaway sub-daily historical snapshots.

Zero external dependencies: uses Python 3 standard library (urllib.request, json, base64).
"""

import argparse
import base64
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LIFECYCLE_RULES = REPO_ROOT / "tools" / "backup-dr" / "b2-lifecycle-rules.json"


def get_credentials(args):
    key_id = (
        args.key_id
        or os.environ.get("B2_APPLICATION_KEY_ID")
        or os.environ.get("BACKUP_DEST_ACCESS_KEY_ID")
        or os.environ.get("B2_KEY_ID")
    )
    key = (
        args.application_key
        or os.environ.get("B2_APPLICATION_KEY")
        or os.environ.get("BACKUP_DEST_SECRET_ACCESS_KEY")
    )
    bucket_name = (
        args.bucket
        or os.environ.get("B2_BUCKET_NAME")
        or os.environ.get("BACKUP_DEST_BUCKET")
        or "jacobmiller22-secure-backup"
    )

    if not key_id or not key:
        print("[-] ERROR: Backblaze B2 credentials not found.", file=sys.stderr)
        print("    Provide --key-id and --application-key, or set", file=sys.stderr)
        print("    B2_APPLICATION_KEY_ID and B2_APPLICATION_KEY in the environment.", file=sys.stderr)
        sys.exit(1)

    return key_id.strip(), key.strip(), bucket_name.strip()


def b2_authorize(key_id, key):
    auth_header = base64.b64encode(f"{key_id}:{key}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
        headers={"Authorization": f"Basic {auth_header}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"[-] ERROR: B2 Authorization failed ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)


def b2_get_bucket(auth_data, bucket_name):
    api_url = auth_data["apiUrl"]
    auth_token = auth_data["authorizationToken"]
    account_id = auth_data["accountId"]

    # Allowed bucket info may be directly in auth_data
    allowed = auth_data.get("allowed", {})
    if allowed.get("bucketId") and allowed.get("bucketName") == bucket_name:
        # We know the bucket ID directly
        bucket_id = allowed["bucketId"]
    else:
        bucket_id = None

    req = urllib.request.Request(
        f"{api_url}/b2api/v2/b2_list_buckets",
        data=json.dumps({"accountId": account_id, "bucketId": bucket_id} if bucket_id else {"accountId": account_id}).encode("utf-8"),
        headers={"Authorization": auth_token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for b in data.get("buckets", []):
                if b.get("bucketName") == bucket_name or b.get("bucketId") == bucket_id:
                    return b
            print(f"[-] ERROR: Bucket '{bucket_name}' not found.", file=sys.stderr)
            sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"[-] ERROR: Failed to list buckets ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    key_id, key, bucket_name = get_credentials(args)
    print(f"[+] Authorizing with Backblaze B2 (Key ID: {key_id[:6]}...)...")
    auth_data = b2_authorize(key_id, key)

    capabilities = auth_data.get("allowed", {}).get("capabilities", [])
    name_prefix = auth_data.get("allowed", {}).get("namePrefix") or ""
    print(f"[+] Authorized! Key capabilities: {', '.join(capabilities)}")
    if name_prefix:
        print(f"[+] Scoped name prefix: '{name_prefix}'")

    bucket = b2_get_bucket(auth_data, bucket_name)
    bucket_id = bucket["bucketId"]
    lifecycle_rules = bucket.get("lifecycleRules", [])

    print(f"\n{'='*70}")
    print(f"📦 BUCKET STATUS: {bucket_name} (ID: {bucket_id})")
    print(f"{'='*70}")
    print(f"Bucket Type: {bucket.get('bucketType')}")
    print(f"Default Server-Side Encryption: {bucket.get('defaultServerSideEncryption', {}).get('value', {})}")

    print("\n📋 Current Lifecycle Rules:")
    if not lifecycle_rules:
        print("  ⚠️  NO LIFECYCLE RULES CONFIGURED! Files and versions will accumulate indefinitely.")
    else:
        for idx, rule in enumerate(lifecycle_rules, 1):
            prefix = rule.get("fileNamePrefix", "(all)")
            hide_days = rule.get("daysFromUploadingToHiding")
            del_days = rule.get("daysFromHidingToDeleting")
            cancel_days = rule.get("daysFromStartingToCancelingUnfinishedLargeFiles")
            print(f"  [{idx}] Prefix: '{prefix}'")
            print(f"      - Days from upload to hide: {hide_days if hide_days is not None else 'Never'}")
            print(f"      - Days from hide to delete: {del_days if del_days is not None else 'Never'}")
            if cancel_days:
                print(f"      - Cancel unfinished large files: {cancel_days} days")

    # Inventory versions under prefix
    api_url = auth_data["apiUrl"]
    auth_token = auth_data["authorizationToken"]
    scan_prefix = args.prefix if args.prefix is not None else (name_prefix or "backups")

    print(f"\n🔍 Scanning storage under prefix '{scan_prefix}'...")
    total_size = 0
    total_versions = 0
    action_counts = defaultdict(int)
    file_versions = defaultdict(list)
    prefix_sizes = defaultdict(int)

    start_file_name = None
    start_file_id = None
    while True:
        payload = {"bucketId": bucket_id, "maxFileCount": 1000}
        if scan_prefix:
            payload["prefix"] = scan_prefix
        if start_file_name:
            payload["startFileName"] = start_file_name
            payload["startFileId"] = start_file_id

        req = urllib.request.Request(
            f"{api_url}/b2api/v2/b2_list_file_versions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": auth_token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"[-] Error listing file versions: {e.read().decode('utf-8')}", file=sys.stderr)
            break

        files = data.get("files", [])
        if not files:
            break

        for f in files:
            size = f.get("contentLength", 0)
            action = f.get("action", "unknown")
            fname = f.get("fileName", "")
            total_size += size
            total_versions += 1
            action_counts[action] += 1
            file_versions[fname].append(f)

            # Sub-prefix breakdown
            parts = fname.split("/")
            sub = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
            prefix_sizes[sub] += size

        start_file_name = data.get("nextFileName")
        start_file_id = data.get("nextFileId")
        if not start_file_name:
            break

    total_gb = total_size / (1024**3)
    free_tier_cap_gb = 10.0
    percent_used = (total_gb / free_tier_cap_gb) * 100

    print(f"\n📊 Storage Summary:")
    print(f"  Total Versions Tracked: {total_versions}")
    print(f"  Unique File Paths:      {len(file_versions)}")
    print(f"  Total Data Stored:      {total_gb:.3f} GB ({total_size / (1024**2):.1f} MB)")
    print(f"  Free Tier Quota (10GB): {percent_used:.1f}% used")

    if percent_used >= 95.0:
        print("  🚨 CRITICAL: Storage cap exceeded or near limit! New uploads will be blocked.")
    elif percent_used >= 80.0:
        print("  ⚠️ WARNING: Storage usage above 80% free-tier threshold.")
    else:
        print("  ✅ Storage usage is within safe operating limits.")

    print(f"\n📁 Usage Breakdown by Prefix:")
    for sub, sz in sorted(prefix_sizes.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {sub:30s} {sz / (1024**3):6.3f} GB ({sz / (1024**2):7.1f} MB)")

    # Multi-version check
    multi = {k: v for k, v in file_versions.items() if len(v) > 1}
    if multi:
        print(f"\n⚠️  Non-Current Version Bloat Detected:")
        print(f"  {len(multi)} files contain multiple retained versions:")
        for fname, vers in list(multi.items())[:5]:
            v_sz = sum(x.get("contentLength", 0) for x in vers)
            print(f"    - {fname}: {len(vers)} versions ({v_sz / (1024**2):.1f} MB)")


def cmd_apply(args):
    key_id, key, bucket_name = get_credentials(args)
    print(f"[+] Authorizing with Backblaze B2 (Key ID: {key_id[:6]}...)...")
    auth_data = b2_authorize(key_id, key)

    capabilities = auth_data.get("allowed", {}).get("capabilities", [])
    can_write_buckets = "writeBuckets" in capabilities

    # Target lifecycle rule definition
    rule = {
        "daysFromHidingToDeleting": args.delete_days,
        "daysFromStartingToCancelingUnfinishedLargeFiles": 1,
        "daysFromUploadingToHiding": args.retention_days,
        "fileNamePrefix": args.prefix,
    }
    rules_payload = [rule]

    print(f"\n[+] Desired Lifecycle Policy for '{bucket_name}':")
    print(json.dumps(rules_payload, indent=2))

    if not can_write_buckets:
        print("\n" + "="*70)
        print("⚠️  PERMISSION NOTICE: Current Application Key lacks 'writeBuckets' permission.")
        print("="*70)
        print("Backblaze B2 requires 'writeBuckets' capability (held by the Master Application Key")
        print("or an Admin Application Key) to update bucket-level lifecycle settings.\n")
        print("To apply this lifecycle policy, choose one of the following methods:\n")
        print("Method 1: Run with your Master Application Key:")
        print(f"  python3 {__file__} apply \\")
        print(f"    --key-id <MASTER_KEY_ID> --application-key <MASTER_KEY> \\")
        print(f"    --retention-days {args.retention_days} --delete-days {args.delete_days}\n")
        print("Method 2: Use the Backblaze B2 CLI:")
        print(f"  b2 update-bucket --lifecycleRule '{json.dumps(rule)}' {bucket_name} allPrivate\n")
        print("Method 3: In the Backblaze B2 Web Console:")
        print(f"  1. Navigate to: https://secure.backblaze.com/b2_buckets.htm")
        print(f"  2. Click 'Lifecycle Settings' next to bucket '{bucket_name}'")
        print(f"  3. Set Prefix: '{args.prefix}'")
        print(f"  4. Set 'Days until Hiding': {args.retention_days}")
        print(f"  5. Set 'Days until Deleting': {args.delete_days}")
        print(f"  6. Save Changes.")
        print("="*70)
        return

    # Execute b2_update_bucket
    api_url = auth_data["apiUrl"]
    auth_token = auth_data["authorizationToken"]
    account_id = auth_data["accountId"]
    bucket = b2_get_bucket(auth_data, bucket_name)
    bucket_id = bucket["bucketId"]

    payload = {
        "accountId": account_id,
        "bucketId": bucket_id,
        "lifecycleRules": rules_payload,
    }

    req = urllib.request.Request(
        f"{api_url}/b2api/v2/b2_update_bucket",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": auth_token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            print(f"\n✅ Lifecycle policies updated successfully on '{bucket_name}'!")
            print(json.dumps(res.get("lifecycleRules", []), indent=2))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"[-] ERROR: b2_update_bucket failed ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)


def cmd_prune(args):
    key_id, key, bucket_name = get_credentials(args)
    print(f"[+] Authorizing with Backblaze B2 (Key ID: {key_id[:6]}...)...")
    auth_data = b2_authorize(key_id, key)

    capabilities = auth_data.get("allowed", {}).get("capabilities", [])
    if "deleteFiles" not in capabilities:
        print("[-] ERROR: Current key lacks 'deleteFiles' capability.", file=sys.stderr)
        sys.exit(1)

    name_prefix = auth_data.get("allowed", {}).get("namePrefix") or ""
    scan_prefix = args.prefix if args.prefix is not None else (name_prefix or "backups")
    bucket = b2_get_bucket(auth_data, bucket_name)
    bucket_id = bucket["bucketId"]
    api_url = auth_data["apiUrl"]
    auth_token = auth_data["authorizationToken"]

    print(f"[+] Scanning file versions under prefix '{scan_prefix}'...")
    all_versions = []
    start_file_name = None
    start_file_id = None
    while True:
        payload = {"bucketId": bucket_id, "maxFileCount": 1000}
        if scan_prefix:
            payload["prefix"] = scan_prefix
        if start_file_name:
            payload["startFileName"] = start_file_name
            payload["startFileId"] = start_file_id

        req = urllib.request.Request(
            f"{api_url}/b2api/v2/b2_list_file_versions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": auth_token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"[-] Error listing file versions: {e.read().decode('utf-8')}", file=sys.stderr)
            break

        files = data.get("files", [])
        if not files:
            break
        all_versions.extend(files)

        start_file_name = data.get("nextFileName")
        start_file_id = data.get("nextFileId")
        if not start_file_name:
            break

    print(f"[+] Total versions found: {len(all_versions)}")

    # Group by fileName
    by_filename = defaultdict(list)
    for v in all_versions:
        by_filename[v["fileName"]].append(v)

    to_delete = []

    # 1. Prune obsolete pre-migration multi-version files
    # E.g. backups/actual/data-backup.zip.enc and backups/vw/vw-db-backup.sqlite3.enc
    for fname, versions in by_filename.items():
        if fname.endswith("data-backup.zip.enc") or fname.endswith("vw-db-backup.sqlite3.enc"):
            # Obsolete files: all versions can be purged
            for v in versions:
                to_delete.append((v, "Obsolete pre-migration archive"))

    # 2. Thin out runaway sub-daily backups (e.g. 15-minute Actual backups)
    # Target pattern: backups/actual/actual-backup-YYYY-MM-DD_HH-MM-SS.tar.gz.enc
    actual_backups_by_day = defaultdict(list)
    for fname, versions in by_filename.items():
        if "actual-backup-" in fname and fname.endswith(".tar.gz.enc"):
            # Extract day
            parts = fname.split("actual-backup-")
            if len(parts) == 2:
                day = parts[1].split("_")[0]
                # Each is a single version file
                for v in versions:
                    actual_backups_by_day[day].append(v)

    # Determine cutoff for keeping all sub-daily files (e.g. keep all from last 24h)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    days_sorted = sorted(actual_backups_by_day.keys())

    for day in days_sorted:
        day_files = actual_backups_by_day[day]
        if len(day_files) <= 1:
            continue

        # If it's today, keep all (or recent)
        if day == today_str and not args.prune_today:
            continue

        # Sort by timestamp ascending
        day_files.sort(key=lambda x: x.get("uploadTimestamp", 0))

        # Select one anchor backup to KEEP for this historical day
        # Target closest to 16:00 UTC (the canonical backup hour)
        target_hour = 16
        best_candidate = day_files[-1]  # fallback to latest in day
        best_diff = 999999
        for f in day_files:
            fn = f["fileName"]
            try:
                # actual-backup-YYYY-MM-DD_HH-MM-SS
                time_str = fn.split("_")[1].split(".")[0]
                hour = int(time_str.split("-")[0])
                diff = abs(hour - target_hour)
                if diff < best_diff:
                    best_diff = diff
                    best_candidate = f
            except Exception:
                pass

        # Mark all other sub-daily files for deletion
        for f in day_files:
            if f["fileId"] != best_candidate["fileId"]:
                to_delete.append((f, f"Redundant sub-daily snapshot on {day} (keeping {best_candidate['fileName']})"))

    # Summary of planned deletions
    delete_size = sum(v["contentLength"] for v, _ in to_delete)
    print("\n" + "="*70)
    print(f"🧹 PRUNE CANDIDATES SUMMARY ({'DRY RUN' if not args.execute else 'LIVE EXECUTION'})")
    print("="*70)
    print(f"Total versions to delete: {len(to_delete)}")
    print(f"Total space to reclaim:   {delete_size / (1024**3):.3f} GB ({delete_size / (1024**2):.1f} MB)")

    if not to_delete:
        print("[+] Nothing to prune. Storage is clean!")
        return

    if not args.execute:
        print("\n[!] This was a DRY RUN. No files were deleted.")
        print("    To perform actual deletion and reclaim space, re-run with --execute:")
        print(f"    python3 {__file__} prune --execute")
        return

    print(f"\n[+] Executing deletion of {len(to_delete)} versions...")
    deleted_count = 0
    reclaimed_bytes = 0
    for idx, (v, reason) in enumerate(to_delete, 1):
        del_payload = {"fileName": v["fileName"], "fileId": v["fileId"]}
        req = urllib.request.Request(
            f"{api_url}/b2api/v2/b2_delete_file_version",
            data=json.dumps(del_payload).encode("utf-8"),
            headers={"Authorization": auth_token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                deleted_count += 1
                reclaimed_bytes += v["contentLength"]
                if idx % 50 == 0 or idx == len(to_delete):
                    print(f"  [{idx}/{len(to_delete)}] Deleted {deleted_count} versions ({reclaimed_bytes / (1024**2):.1f} MB reclaimed)...")
        except urllib.error.HTTPError as e:
            print(f"  [-] Failed to delete {v['fileName']} ({v['fileId']}): {e.read().decode('utf-8')}", file=sys.stderr)

    print(f"\n✅ Pruning complete! Deleted {deleted_count} versions, reclaimed {reclaimed_bytes / (1024**3):.3f} GB ({reclaimed_bytes / (1024**2):.1f} MB).")


def main():
    parser = argparse.ArgumentParser(description="Backblaze B2 Lifecycle & Retention Manager")
    parser.add_argument("--key-id", help="B2 Application Key ID")
    parser.add_argument("--application-key", help="B2 Application Key")
    parser.add_argument("--bucket", help="B2 Bucket Name (default: jacobmiller22-secure-backup)")
    parser.add_argument("--prefix", default="backups/", help="Object prefix (default: 'backups/')")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Inspect bucket lifecycle rules and storage metrics")

    # apply
    p_apply = subparsers.add_parser("apply", help="Apply declarative B2 lifecycle policies")
    p_apply.add_argument("--retention-days", type=int, default=30, help="Days until version is hidden (default: 30)")
    p_apply.add_argument("--delete-days", type=int, default=1, help="Days until hidden version is deleted (default: 1)")

    # prune
    p_prune = subparsers.add_parser("prune", help="Clean up obsolete versions and redundant sub-daily snapshots")
    p_prune.add_argument("--execute", action="store_true", help="Perform real deletion (default is dry-run)")
    p_prune.add_argument("--prune-today", action="store_true", help="Also prune redundant snapshots from today")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "apply":
        cmd_apply(args)
    elif args.command == "prune":
        cmd_prune(args)


if __name__ == "__main__":
    main()
