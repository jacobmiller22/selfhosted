# Reusable Self-Hosted Backup Runner (`tools/backup-runner`)

A canonical, reusable backup runner engine and Docker image consolidating all backup operations across self-hosted services into a single source of truth.

---

## Features

- **Alpine 3.21 Base**: Lightweight (~15MB compressed), pre-loaded with `bash`, `curl`, `openssl`, `sqlite`, `tar`, `rclone`, `ca-certificates`, and `tzdata`.
- **Declarative Backup Strategies** (`BACKUP_MODE`):
  - `sqlite-auto`: Automatically scans `${BACKUP_SOURCE_DIR}` for `*.sqlite`, `*.sqlite3`, and `*.db` databases. Performs live online snapshots via `sqlite3 <db> ".backup <dest>"`, copies non-database assets (`*.blob`, `*.pem`, `*.json`, config files), and ignores transient journal files (`-wal`, `-shm`, `-journal`).
  - `filesystem`: Recursively stages directory trees without database operations.
  - `hook`: Executes a pre-backup script (e.g. `/hooks/pre-backup.sh <staging_dir>`) for native CLI dumps (e.g. PostgreSQL `pg_dump`, CouchDB).
- **Strict Shell Safety**: Runs with `set -euo pipefail`.
- **Guaranteed Staging Lifecycle**: Staging directories are cleaned up on both normal termination and failures via bash `EXIT` traps.
- **Active Failure Notification**: ERR trap dispatches rich JSON embeds to Discord webhooks (`DISCORD_WEBHOOK_URL`).
- **Standardized Encryption**: Zero-dependency OpenSSL AES-256-CBC PBKDF2 (`-iter 100000`, `-md sha256`, `-salt`) matching [`docs/RESTORE.md`](../../docs/RESTORE.md).
- **Cloud Rotation & Pruning**: Uploads directly to S3 / Backblaze B2 using `rclone copyto` with `--s3-no-check-bucket` and executes automated retention pruning via `prune_remote_backups()`.
- **Safety Upload Verification Latch**: Ensures remote snapshot pruning runs strictly AFTER the newly created backup has uploaded and its presence on remote storage is verified.
- **Dry-Run Simulation**: Supports `DRY_RUN=true` to simulate pruning operations and audit candidates without deleting remote files.
- **Dead Man's Snitch / Healthchecks.io**: Automated success pings (`HEALTHCHECK_PING_URL`).
- **Dynamic Crontab & Secret Isolation**: Entrypoint securely writes environment variables to `/run/secrets/env_vars` (mode `0600`) and executes cron jobs.
- **Signal Handling**: Graceful shutdown on `SIGTERM` and `SIGINT`.

---

## Configuration Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SERVICE_NAME` | `unknown-service` | Service identifier used in log output, archive naming, and notifications. |
| `BACKUP_MODE` | `sqlite-auto` | Declarative strategy: `sqlite-auto`, `filesystem`, or `hook`. |
| `BACKUP_SOURCE_DIR` | `/data` | Directory to back up (used by `sqlite-auto` and `filesystem`). |
| `BACKUP_PASSPHRASE` | *(Required)* | Master encryption passphrase. Falls back to `BACKUP_ENCRYPTION_KEY`. |
| `PRE_BACKUP_SCRIPT` | `/hooks/pre-backup.sh` | Hook script executed when `BACKUP_MODE=hook`. |
| `CRON_SCHEDULE` | `0 16 * * *` | Cron schedule string (runs in UTC by default). |
| `BACKUP_ON_STARTUP` | `false` | Run an immediate backup upon container startup before scheduling. |
| `BACKUP_RETENTION_DAYS` | `30` | Number of days to retain remote snapshot archives before pruning. |
| `DRY_RUN` | `false` | If `true`, simulates archive pruning via `rclone --dry-run` without deleting remote files. |
| `DISCORD_WEBHOOK_URL` | *(Optional)* | Discord webhook URL for failure alert embeds. |
| `HEALTHCHECK_PING_URL` | *(Optional)* | URL to ping upon successful backup completion. |
| `BACKUP_DEST_BUCKET` | *(Optional)* | S3 / B2 bucket name for remote storage. |
| `BACKUP_DEST_ENDPOINT` | *(Optional)* | S3 / B2 endpoint URL. |
| `BACKUP_DEST_ACCESS_KEY_ID` | *(Optional)* | S3 / B2 Access Key ID. |
| `BACKUP_DEST_SECRET_ACCESS_KEY` | *(Optional)* | S3 / B2 Secret Access Key. |
| `BACKUP_DEST_PREFIX` | `backups/${SERVICE_NAME}` | Prefix / folder path within the destination bucket. |
| `B2_DEST_PATH` | *(Optional)* | Explicit remote destination path (e.g. `b2:bucket/backups/actual`). |

---

## Remote Retention Policy & Pruning Mechanics

The backup runner includes automated remote snapshot retention management in `tools/backup-runner/backup-engine.sh` via the `prune_remote_backups()` routine:

1. **Ordering & Safety Latch**:
   - Remote archive pruning is gated by a strict ordering latch (`BACKUP_UPLOAD_VERIFIED=true`).
   - Pruning executes strictly AFTER the new backup snapshot has been created, uploaded, and verified on the remote storage backend (via `rclone lsf` or `aws s3 ls`).
   - If the new backup creation or cloud upload fails, pruning is immediately aborted, preventing any scenario where existing backups are deleted after an upload failure.

2. **Age-Based Pruning (`rclone delete`)**:
   - Queries candidate archives using `rclone lsl <remote> --min-age ${BACKUP_RETENTION_DAYS}d`.
   - Logs candidate archives with timestamp and size.
   - Deletes snapshots exceeding the retention period:
     ```bash
     rclone delete "${B2_DEST_PATH}" --min-age "${BACKUP_RETENTION_DAYS}d"
     ```

3. **Bucket Cleanup (`rclone cleanup`)**:
   - Calls `rclone cleanup` on the target remote to remove uncompleted multipart uploads and old version fragments where supported by the storage backend (e.g. Backblaze B2).

4. **Dry-Run Simulation (`DRY_RUN=true` or `--dry-run`)**:
   - When enabled, appends `--dry-run` to all `rclone` operations.
   - Discovers and logs candidate archives without deleting any files from remote storage.

---

## Restoration

All backups generated by this runner can be decrypted with zero proprietary dependencies using standard OpenSSL and tar as documented in [`docs/RESTORE.md`](../../docs/RESTORE.md):

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in <archive-name>.tar.gz.enc \
  -pass env:BACKUP_PASSPHRASE | \
  tar -xz -C ./extracted
```

---

## Verification & Testing

Execute the comprehensive test harness locally:

```bash
bash tools/backup-runner/test-backup-restore.sh
```
