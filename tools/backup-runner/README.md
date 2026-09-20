# Universal Reusable Backup Runner (`tools/backup-runner`)

A canonical, reusable backup runner engine and Docker image consolidating all backup operations across self-hosted services into a single, declarative source of truth.

---

## 1. Features & Architectural Guarantees

- **Alpine 3.21 Base**: Ultra-lightweight container image (~45MB), pre-loaded with `bash`, `curl`, `openssl`, `sqlite`, `tar`, `rclone`, `ca-certificates`, and `tzdata`.
- **Declarative Backup Strategies** (`BACKUP_MODE`):
  - `sqlite-auto`: Automatically scans `${BACKUP_SOURCE_DIR}` for `*.sqlite`, `*.sqlite3`, and `*.db` databases. Performs live online snapshots via `sqlite3 <db> ".backup <dest>"`, copies accompanying non-database assets (`*.blob`, `*.pem`, `*.json`, configs), and ignores transient journal files (`-wal`, `-shm`, `-journal`).
  - `filesystem`: Recursively stages entire directory trees without database operations via `cp -a`.
  - `hook`: Executes an external pre-backup script (e.g. `/hooks/pre-backup.sh <staging_dir>`) for native CLI dumps (e.g. PostgreSQL `pg_dump`, CouchDB, MongoDB `mongodump`).
- **Strict Shell Safety**: Runs with `set -euo pipefail` throughout all execution paths.
- **Guaranteed Staging Lifecycle**: Staging directories (`/tmp/backup-staging-...`) are cleaned up on both normal termination and runtime failures via bash `EXIT` traps.
- **Active Failure Notification**: ERR trap dispatches rich JSON embeds to Discord webhooks (`DISCORD_WEBHOOK_URL`) with host identifier (`bjorn`), offending command, line number, and exit code.
- **Standardized Zero-Dependency Encryption**: Standard POSIX OpenSSL AES-256-CBC PBKDF2 (`-iter 100000`, `-md sha256`, `-salt`) matching [`docs/RESTORE.md`](../../docs/RESTORE.md).
- **Cloud Rotation & Verification**: Uploads directly to S3 / Backblaze B2 using `rclone copyto` with `--s3-no-check-bucket` and affirmatively verifies remote presence before signaling success.
- **Server-Side Lifecycle Retention**: Snapshot retention (30 days) is managed natively by Backblaze B2 bucket lifecycle rules, eliminating destructive client-side deletion commands and enforcing the principle of least privilege.
- **Dead Man's Snitch / Healthchecks.io**: Automated success pings (`HEALTHCHECK_PING_URL`).
- **Dynamic Crontab & Secret Isolation**: Entrypoint securely exports environment variables to `/run/secrets/env_vars` (mode `0600`) and executes cron jobs under crond.
- **Signal Handling**: Graceful shutdown on `SIGTERM` and `SIGINT`.

---

## 2. Frictionless Service Enrollment Runbook

Enrolling any containerized service or compose stack into automated encrypted cloud backups requires **under 15 lines of YAML** without writing any custom code or shell scripts.

### 2.1 Copy-Pasteable Compose Snippet (<15 Lines)

Add this sidecar service definition directly to your stack's `compose.yml`:

```yaml
  my-service-backup:
    build: ../tools/backup-runner
    container_name: my-service-backup
    restart: unless-stopped
    environment:
      - SERVICE_NAME=my-service
      - BACKUP_MODE=sqlite-auto
      - BACKUP_PASSPHRASE=${BACKUP_PASSPHRASE}
      - B2_APPLICATION_KEY_ID=${B2_APPLICATION_KEY_ID}
      - B2_APPLICATION_KEY=${B2_APPLICATION_KEY}
      - B2_BUCKET_NAME=${B2_BUCKET_NAME}
      - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL:-}
    volumes:
      - service-data:/data:ro
```

*Total lines: 14. Defaults automatically supply `BACKUP_SOURCE_DIR=/data`, `CRON_SCHEDULE=0 16 * * *`, and default cloud prefix `backups/my-service`.*

### 2.2 Enrollment Checklist
1. **Choose Strategy**:
   - Use `BACKUP_MODE=sqlite-auto` if the service uses SQLite (e.g. Actual Budget, Vaultwarden, Home Assistant, Nginx Proxy Manager).
   - Use `BACKUP_MODE=filesystem` if the service stores flat files or document shards (e.g. Obsidian CouchDB LiveSync).
   - Use `BACKUP_MODE=hook` if the service requires an active database dump utility (e.g. PostgreSQL, MongoDB).
2. **Mount Data Volume**: Mount the target volume to `/data:ro` (or set `BACKUP_SOURCE_DIR` to your chosen mount point).
3. **Environment Secrets**: Ensure standard secrets (`BACKUP_PASSPHRASE`, `B2_APPLICATION_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME`) are set in Coolify or your `.env` file.
4. **Deploy**: Start or update the stack with `docker compose up -d`.

---

## 3. Volume Mounting Best Practices & `:ro` Read-Only Security Model

> [!IMPORTANT]
> **Always mount application data volumes into backup runner sidecars using the `:ro` (read-only) flag.**

### Why Read-Only Mounts are Mandatory:
1. **Production Immutability**: Read-only mounts guarantee that the backup container cannot accidentally delete, overwrite, or corrupt production data files under any circumstance.
2. **Crash & Bug Isolation**: Even in the event of an unhandled script failure, misconfiguration, or container compromise, the application storage volume remains physically untouched.
3. **Lock Contention Elimination**: In SQLite databases, `sqlite3 <db> ".backup <dest>"` reads pages safely using SQLite's online backup API. Mounting `:ro` ensures the backup engine cannot write temporary `-wal` or `-shm` locks into the application directory.
4. **Principle of Least Privilege**: A backup process is strictly a data consumer; granting write permissions violates fundamental security architecture.

---

## 4. Declarative Backup Strategies Deep Dive

The runner engine provides three declarative modes configured via `BACKUP_MODE`:

### 4.1 `sqlite-auto` (Default)
Ideal for services using SQLite databases alongside companion asset files (Actual Budget, Vaultwarden, Home Assistant, Nginx Proxy Manager).

- **Database Discovery**: Automatically discovers any file ending in `.sqlite`, `.sqlite3`, or `.db` in `${BACKUP_SOURCE_DIR}` and subdirectories.
- **Online Non-Blocking Snapshot**: Invokes `sqlite3 <db> ".backup <dest>"` on each database, guaranteeing transactional consistency without taking the service offline.
- **Companion Asset Staging**: Recursively copies non-database files (`*.blob`, `*.pem`, `*.json`, YAML, configs) into the staging directory, mirroring the directory structure.
- **Transient File Exclusion**: Automatically ignores SQLite transient write-ahead log and journal files (`*-wal`, `*-shm`, `*-journal`).

### 4.2 `filesystem`
Ideal for directory trees containing flat files, static documents, or database storage engines where directory-level copies are safe (e.g. Obsidian CouchDB LiveSync).

- **Recursive Tree Copy**: Copies all files and subdirectories from `${BACKUP_SOURCE_DIR}` to `${STAGING_DIR}` using `cp -a`.
- **Permission Preservation**: Preserves original POSIX file modes, ownership metadata, and symlinks.

### 4.3 `hook`
Ideal for stateful database servers requiring native client CLI utilities to export consistent logical dumps (PostgreSQL, CouchDB, MongoDB).

- **Invocation Contract**: The engine passes the staging directory path as argument `$1` to the script specified in `PRE_BACKUP_SCRIPT` (default: `/hooks/pre-backup.sh`).
- **Automated Encryption & Upload**: Once the hook script exits with status `0`, the runner engine automatically packages, encrypts, and uploads all artifacts placed into `$1`.

---

## 5. Non-SQLite Pre-Backup Hooks Guide

When running databases that cannot be snapshotted directly from the filesystem, use `BACKUP_MODE=hook`. The script receives the staging directory as `$1`.

### 5.1 PostgreSQL Pre-Backup Hook
Dumps a PostgreSQL database using `pg_dump` via `docker exec`:

```bash
#!/usr/bin/env bash
# /hooks/pre-backup-postgres.sh
set -euo pipefail

STAGING_DIR="${1:-/staging}"
mkdir -p "${STAGING_DIR}"

echo "[+] Dumping PostgreSQL database from container postgres-db..."
docker exec postgres-db pg_dump -U postgres -d my_database > "${STAGING_DIR}/database.sql"
echo "[+] PostgreSQL dump completed: ${STAGING_DIR}/database.sql"
```

*Compose wiring:*
```yaml
  postgres-backup:
    build: ../tools/backup-runner
    container_name: postgres-backup
    restart: unless-stopped
    environment:
      - SERVICE_NAME=postgres
      - BACKUP_MODE=hook
      - PRE_BACKUP_SCRIPT=/hooks/pre-backup-postgres.sh
      - BACKUP_PASSPHRASE=${BACKUP_PASSPHRASE}
      - B2_APPLICATION_KEY_ID=${B2_APPLICATION_KEY_ID}
      - B2_APPLICATION_KEY=${B2_APPLICATION_KEY}
      - B2_BUCKET_NAME=${B2_BUCKET_NAME}
    volumes:
      - ./hooks:/hooks:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

### 5.2 CouchDB Pre-Backup Hook
Triggers CouchDB compaction via HTTP API and stages data:

```bash
#!/usr/bin/env bash
# /hooks/pre-backup-couchdb.sh
set -euo pipefail

STAGING_DIR="${1:-/staging}"
mkdir -p "${STAGING_DIR}"

echo "[+] Triggering compaction on CouchDB databases..."
curl -fsS -u "${COUCHDB_USER}:${COUCHDB_PASSWORD}" -X POST \
  http://couchdb:5984/_all_dbs | jq -r '.[]' | while read -r db; do
    curl -fsS -u "${COUCHDB_USER}:${COUCHDB_PASSWORD}" -H "Content-Type: application/json" \
      -X POST "http://couchdb:5984/${db}/_compact" || true
done

echo "[+] Copying CouchDB data files to staging..."
cp -a /opt/couchdb/data/. "${STAGING_DIR}/"
```

### 5.3 MongoDB Pre-Backup Hook
Dumps a MongoDB instance using `mongodump`:

```bash
#!/usr/bin/env bash
# /hooks/pre-backup-mongo.sh
set -euo pipefail

STAGING_DIR="${1:-/staging}"
mkdir -p "${STAGING_DIR}"

echo "[+] Exporting MongoDB database dump..."
docker exec mongo-db mongodump --archive="${STAGING_DIR}/mongodb.archive" --gzip
echo "[+] MongoDB archive created: ${STAGING_DIR}/mongodb.archive"
```

---

## 6. Complete Configuration & Environment Variable Reference

| Canonical Variable | Alternate Aliases / Fallbacks | Default | Description |
| :--- | :--- | :--- | :--- |
| `SERVICE_NAME` | `BACKUP_TARGET_NAME` | `unknown-service` | Service identifier used in log output, archive naming, and remote object paths. |
| `BACKUP_MODE` | — | `sqlite-auto` | Declarative strategy: `sqlite-auto`, `filesystem`, or `hook`. |
| `BACKUP_SOURCE_DIR` | — | `/data` | Directory to snapshot (used by `sqlite-auto` and `filesystem`). |
| `BACKUP_PASSPHRASE` | `BACKUP_ENCRYPTION_KEY` | *(Required)* | Master encryption passphrase for OpenSSL PBKDF2 AES-256-CBC. |
| `CRON_SCHEDULE` | `BACKUP_CRON` | `0 16 * * *` | Cron schedule expression (runs in UTC within container crond). |
| `BACKUP_ON_STARTUP` | — | `false` | When `true`, runs an immediate backup on container launch before starting cron. |
| `BACKUP_DEST_BUCKET` | `B2_BUCKET_NAME`, `B2_BUCKET`, `RCLONE_B2_BUCKET` | *(Optional)* | Destination Backblaze B2 / S3 bucket name. |
| `BACKUP_DEST_ACCESS_KEY_ID` | `B2_APPLICATION_KEY_ID`, `B2_KEY_ID` | *(Optional)* | Cloud storage Access Key ID / Application Key ID. |
| `BACKUP_DEST_SECRET_ACCESS_KEY` | `B2_APPLICATION_KEY` | *(Optional)* | Cloud storage Secret Access Key / Application Key. |
| `BACKUP_DEST_ENDPOINT` | — | *(Optional)* | S3 endpoint URL (e.g. `https://s3.us-east-005.backblazeb2.com`). |
| `BACKUP_DEST_PREFIX` | — | `backups/${SERVICE_NAME}` | Prefix / folder path inside destination bucket. |
| `B2_DEST_PATH` | — | *(Optional)* | Explicit full remote destination path (e.g. `b2:my-bucket/backups/actual`). |
| `PRE_BACKUP_SCRIPT` | `BACKUP_PRE_HOOK`, `HOOK_SCRIPT` | `/hooks/pre-backup.sh` | Hook script path executed when `BACKUP_MODE=hook`. |
| `DISCORD_WEBHOOK_URL` | — | *(Optional)* | Discord webhook URL for rich JSON failure alert embeds. |
| `HEALTHCHECK_PING_URL` | `HEALTHCHECKS_URL` | *(Optional)* | Healthchecks.io / Dead Man's Snitch ping URL on verified completion. |

---

## 7. Backblaze B2 Server-Side Lifecycle Rules & Least Privilege

Snapshot retention is managed **server-side** by Backblaze B2 bucket lifecycle rules rather than client-side container pruning:

1. **Principle of Least Privilege (Ransomware Defense)**:
   - Backup containers on host `bjorn` only require `writeFiles` (plus `listFiles` and `readFiles` for upload verification).
   - Containers **DO NOT possess `deleteFiles` capability**.
   - If container credentials or the server host are ever compromised, historical backups on Backblaze B2 cannot be wiped or held for ransom.

2. **Zero Client Compute & Quota Overhead**:
   - Eliminates recurring `rclone delete` and `rclone lsl` sweeps on the server.
   - Eliminates unnecessary Class B/C API transactions and latency.

3. **B2 Lifecycle Rule Configuration**:
   - `daysFromUploadingToHiding: 30` (marks versions older than 30 days as hidden).
   - `daysFromHidingToDeleting: 1` (permanently deletes hidden versions after 1 day).
   - See [`docs/BACKUP_ARCHITECTURE.md`](../../docs/BACKUP_ARCHITECTURE.md) Section 7 for full JSON rules and CLI instructions.

---

## 8. Zero-Dependency Cold-Storage Restoration

All backups generated by this runner can be decrypted with zero proprietary dependencies using standard OpenSSL and tar as documented in [`docs/RESTORE.md`](../../docs/RESTORE.md):

```bash
# Decrypt and extract to ./extracted directory:
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in <service>-backup-<timestamp>.tar.gz.enc \
  -pass env:BACKUP_PASSPHRASE | \
  tar -xz -C ./extracted
```

---

## 9. Verification & Testing

Execute the comprehensive test harness locally to validate all declarative strategies, encryption roundtrips, staging lifecycle cleanup, and fallback variables:

```bash
bash tools/backup-runner/test-backup-restore.sh
```
