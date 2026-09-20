# Self-Hosted Backup Architecture & Disaster Recovery Specification

This document details the architectural design, declarative strategy engine, security model, alerting protocols, and service inventories for all self-hosted infrastructure running on host server **`bjorn`**.

---

## 1. Executive Summary & Problem Statement

The self-hosted infrastructure hosts critical services including financial management (**Actual Budget**), credentials and passwords (**Vaultwarden**), home automation (**Home Assistant**), reverse proxy routing with SSL termination (**Nginx Proxy Manager**), and note replication (**Obsidian CouchDB LiveSync**), all coordinated through **Coolify**.

### Legacy Shortcomings (`volback`):
1. **Single-Point Overwrite**: Backups wrote to a fixed, static object key (`backups/actual/data-backup.zip.enc` and `backups/vw/vw-db-backup.sqlite3.enc`), destroying previous recovery points daily.
2. **Proprietary Encryption Format**: Backups relied on `volback` (a custom Go tool using Argon2id with custom binary framing + AES-128-CTR). Recovery in an emergency required compiling custom Go binaries.
3. **Silent Failures**: Shell scripts lacked `set -euo pipefail` and error traps. If backups failed, the container exited 0 and no alerts were triggered.
4. **Live SQLite Inconsistency**: Backups copied live SQLite databases via raw `cp -r` during active writes, risking corrupt pages and invalid headers.
5. **Coverage Gaps**: Home Assistant, Nginx Proxy Manager, Obsidian LiveSync, and Coolify's PostgreSQL database had no automated backups.

---

## 2. Target Architecture Overview

The system architecture standardizes on a single canonical, reusable backup runner engine (`tools/backup-runner`), built upon an Alpine 3.21 base image (~45MB). Each service deploys an isolated sidecar instance of this runner configured entirely through declarative environment variables and read-only volume mounts (`:ro`).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Host Server: bjorn (Docker & Coolify Engine)                                           │
│                                                                                        │
│  ┌─────────────────────────┐          ┌─────────────────────────────────────────────┐  │
│  │ Application Volumes     │          │ Canonical Universal Backup Runner Engine     │  │
│  │ (Read-Only :ro Mounts)  │          │ (tools/backup-runner - Alpine 3.21, ~45MB)   │  │
│  ├─────────────────────────┤          ├─────────────────────────────────────────────┤  │
│  │ - Actual Budget Data    │─────────▶│ 1. Declarative Discovery & Snapshot Engine: │  │
│  │ - Vaultwarden Data      │          │    • sqlite-auto: online .backup + assets   │  │
│  │ - Home Assistant Config │─────────▶│    • filesystem: recursive file trees       │  │
│  │ - NPM Data & Certs      │          │    • hook: custom dump scripts (Postgres/DB)│  │
│  │ - Obsidian CouchDB Data │─────────▶│ 2. Guaranteed Cleanup Lifecycle (EXIT trap)│  │
│  │ - Coolify Postgres DB   │          │ 3. POSIX OpenSSL AES-256-CBC PBKDF2 Encrypt │  │
│  └─────────────────────────┘          │ 4. Direct Upload & Verification via rclone  │  │
│                                       │ 5. Active Failure Alert (ERR trap ──▶ Discord│  │
│                                       │ 6. Passive Silence Ping ──▶ Healthchecks.io │  │
│                                       └─────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┬─────────────────────────────────┘
                                                       │ TLS / HTTPS S3 API (rclone)
                                                       ▼
                                      ┌──────────────────────────────────────────────────┐
                                      │ Backblaze B2 (Cloud Storage Bucket)              │
                                      │  - Bucket: jacobmiller22-secure-backup           │
                                      │  - Prefix: backups/<service>/<archive>.tar.gz.enc│
                                      │  - Non-destructive ISO timestamp naming          │
                                      │  - 30-Day Server-Side Lifecycle Rules (Auto-Prune│
                                      │  - Least Privilege: Containers lack deleteFiles  │
                                      └──────────────────────────────────────────────────┘
```

### 2.1 Process Execution Lifecycle

```
[Cron Trigger (crond)] ──▶ [/app/backup-engine.sh]
                                  │
                                  ├─▶ [1. Trap Setup] (EXIT: rm -rf staging, ERR: Discord Webhook)
                                  │
                                  ├─▶ [2. Strategy Execution]
                                  │       ├─ sqlite-auto: sqlite3 .backup + copy non-db assets
                                  │       ├─ filesystem:  cp -a tree to staging
                                  │       └─ hook:        run pre-backup hook script
                                  │
                                  ├─▶ [3. Archive & Encrypt]
                                  │       tar -cz | openssl enc -aes-256-cbc -pbkdf2 -iter 100000
                                  │
                                  ├─▶ [4. Cloud Upload & Verification]
                                  │       rclone copyto --s3-no-check-bucket ──▶ Verify existence
                                  │
                                  ├─▶ [5. Telemetry & Success Ping]
                                  │       curl -fsS -m 10 --retry 3 "${HEALTHCHECK_PING_URL}"
                                  │
                                  └─▶ [6. Guaranteed Cleanup] (rm -rf staging & scratchpad)
```

---

## 3. Standardized OpenSSL Encryption Specification

To guarantee zero-dependency disaster recovery from any computer in the world (macOS, Linux, BSD, or Windows WSL), all backups standardize on POSIX-native OpenSSL encryption.

### 3.1 Encryption Parameters
- **Cipher**: `aes-256-cbc` (256-bit Advanced Encryption Standard in Cipher Block Chaining mode).
- **Key Derivation**: PBKDF2 (Password-Based Key Derivation Function 2) with HMAC-SHA256.
- **Iteration Count**: `100000` (resistant to brute-force dictionary attacks).
- **Salt**: Cryptographically random 8-byte salt (standard OpenSSL `Salted__` header format).

### 3.2 Canonical Encryption Command
```bash
tar -cz -C "${STAGING_DIR}" . | \
  openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
  -pass env:BACKUP_PASSPHRASE \
  -out "${ARCHIVE_DEST}/${SERVICE_NAME}-backup-${TIMESTAMP}.tar.gz.enc"
```

### 3.3 Canonical Decryption Command
```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${SERVICE_NAME}-backup-${TIMESTAMP}.tar.gz.enc" \
  -pass env:BACKUP_PASSPHRASE | \
  tar -xz -C "${RESTORE_TARGET}"
```

---

## 4. Security & Offline Passphrase Management

To protect against total host compromise or ransomware:

### 4.1 The Fireproof Wallet Model
1. **Passphrase Separation**: The backup encryption passphrase is **NEVER** committed to Git, hardcoded in Dockerfiles, or recorded in plain text notes on server drives.
2. **Physical Offline Storage**: The master encryption passphrase is hand-written or printed on archival paper stored in a physical fireproof/waterproof document safe at home.
3. **Host Injection**: On the host server (`bjorn`), the passphrase is provided strictly at runtime via Coolify Environment Variables (`BACKUP_PASSPHRASE`), never accessible via world-readable files.
4. **Public Runbook Safety**: All documentation in this repository assumes the reader has physical access to the offline fireproof safe. The procedures describe the exact commands, flags, and paths, leaving only the secret key to be read from the safe.

---

## 5. Failure Alerting & Monitoring Protocols

Backups must never fail silently. The system employs a two-tier alerting strategy: **Active Failure Traps** and **Passive Silence Detection (Dead Man's Snitch)**.

### 5.1 Active Failure Trapping (Discord Webhook)
Every backup script executes under `set -euo pipefail` with an error trap:
```bash
trap 'on_error "$LINENO" "$BASH_COMMAND" "$?"' ERR
```
If any command fails (e.g. SQLite read error, disk full, B2 upload rejection), `on_error` dispatches a structured Discord webhook embed:
- **Title**: `🚨 Backup Failure: <service>`
- **Fields**: Host (`bjorn`), Failed Command, Exit Code, Line Number, and Timestamp.
- **Action**: Exits with non-zero code to trigger Coolify container health failure.

### 5.2 Passive Silence Detection (Dead Man's Snitch / Healthchecks.io)
If the entire server crashes, Docker hangs, or cron fails to trigger, active error traps cannot run.
- Each service backup job is assigned a unique Healthchecks.io endpoint URL.
- Upon successful upload and verification, the script signals the check:
  ```bash
  curl -fsS -m 10 --retry 3 "${HEALTHCHECK_PING_URL}"
  ```
- If no ping is received within 25 hours (daily schedule + 1-hour grace period), Healthchecks.io triggers a Discord notification.

---

## 6. Service Data Inventory & Snapshot Rules

| Service | Persistent Paths on `bjorn` | Snapshot Strategy | Critical Considerations |
| :--- | :--- | :--- | :--- |
| **Actual Budget** | Docker volume `actual-data`:<br>- `server-files/account.sqlite`<br>- `user-files/*.sqlite`<br>- `user-files/*.blob` | Enrolled (`actual-backup` sidecar): `sqlite-auto` mode via `tools/backup-runner`. Run `sqlite3 <db> ".backup <dest>"` for each `.sqlite` file.<br>Copy `.blob` files directly. | Do not use raw `cp` on SQLite DBs while Actual is running. Ownership must be restored as `1000:1000`. |
| **Vaultwarden** | Docker volume `vw-data`:<br>- `db.sqlite3`<br>- `rsa_key.pem` & `rsa_key.pub`<br>- `attachments/`<br>- `sends/`<br>- `config.json` | Enrolled (`vw-backup` sidecar): `sqlite-auto` mode via `tools/backup-runner`. Run `sqlite3 db.sqlite3 ".backup <dest>"` for SQLite.<br>Copy RSA keypair, attachments, and sends directories. | Restoring `db.sqlite3` without `rsa_key.pem` invalidates existing auth/session tokens. |
| **Home Assistant** | Bind mount `./config` (`/config` in container):<br>- `.storage/`<br>- `home-assistant_v2.db`<br>- `configuration.yaml` | Enrolled (`ha-backup` sidecar): `sqlite-auto` mode via `tools/backup-runner`. Automatically snapshots `home-assistant_v2.db` via `sqlite3 .backup`, stages `.storage/` and YAML configs via read-only bind mount (`./config:/config:ro`). | `.storage/` holds all credentials and integration states; must be preserved intact. |
| **Nginx Proxy Manager** | Bind mounts:<br>- `./data` (`database.sqlite`, `keys.json`)<br>- `./letsencrypt` (SSL certificates & keys) | Enrolled (`npm-backup` sidecar): `sqlite-auto` mode via `tools/backup-runner`. Automatically snapshots `database.sqlite` via `sqlite3 .backup`, stages `keys.json` and SSL certificates (`./letsencrypt:/letsencrypt:ro`) via read-only bind mounts (`:ro`). | Restoring certificates prevents Let's Encrypt rate-limiting on rebuilds. |
| **Obsidian LiveSync** | Bind mount `./db/data` (`/opt/couchdb/data`):<br>- `*.couch`<br>- `.shards/`<br>- View indexes | Enrolled (`obsidian-backup` sidecar): `filesystem` mode copy of `/data` via read-only bind mount (`:ro`). | Read-only mount prevents write lock contention during live sync. Ownership must be restored as `5984:5984`. |
| **Coolify State** | Docker container `coolify-db` (Postgres 15) | Enrolled (`pre-backup-coolify.sh` hook): `hook` mode via `tools/backup-runner`. Runs `docker exec coolify-db pg_dump -U coolify -d coolify > /staging/coolify.sql`. | Backs up all service configurations, deployment environments, and secrets. |

---

## 7. Storage Lifecycle & Backblaze B2 Server-Side Retention Policy

- **Target Bucket**: Backblaze B2 (`jacobmiller22-secure-backup`).
- **Archive Path Format**: `backups/<service>/<service>-backup-%Y-%m-%d_%H-%M-%S.tar.gz.enc`
- **Snapshot Retention**: Managed natively via **Backblaze B2 Bucket Lifecycle Rules** (30-day retention).
- **Cold Off-site**: Once per quarter, download the latest archives for physical offline archive.

### 7.1 Server-Side Lifecycle Rules vs. Client-Side Pruning
Snapshot retention is enforced **server-side** by Backblaze B2 rather than having individual backup runner containers execute destructive client-side delete commands:

1. **Principle of Least Privilege & Ransomware Protection**:
   - Application keys injected into Docker containers on `bjorn` only require `writeFiles` (plus `listFiles` and `readFiles` for upload verification).
   - Containers **DO NOT possess `deleteFiles` capability**.
   - If a container on `bjorn` is ever compromised by an attacker or rogue script, existing remote historical backups cannot be purged or held for ransom.
2. **Zero Client Compute & Network Quota Overhead**:
   - Eliminates recurring `rclone delete` or `rclone lsl` scans across all services every day.
   - Eliminates Class B / Class C API transaction charges and network latency on container backup runs.
3. **High Reliability & Self-Healing**:
   - Backblaze B2's storage infrastructure handles expiration and file deletion asynchronously in the background, independent of server uptime or container execution.

### 7.2 Backblaze B2 Lifecycle Configuration Specification
The B2 bucket `jacobmiller22-secure-backup` is configured with the following lifecycle rules:

```json
[
  {
    "daysFromUploadingToHiding": 30,
    "daysFromHidingToDeleting": 1,
    "fileNamePrefix": "backups/"
  }
]
```

- **`daysFromUploadingToHiding: 30`**: Snapshots older than 30 days are automatically hidden (marked as non-current).
- **`daysFromHidingToDeleting: 1`**: Hidden versions are permanently purged after 1 day, maintaining a clean 30-day rolling retention window.

#### Applying Lifecycle Rules via B2 CLI or AWS S3 API
Administrators can inspect or apply lifecycle policies from their management workstation:

```bash
# Using Backblaze B2 CLI:
b2 update-bucket \
  --lifecycleRule '{"daysFromUploadingToHiding": 30, "daysFromHidingToDeleting": 1, "fileNamePrefix": "backups/"}' \
  jacobmiller22-secure-backup allPrivate

# Or using AWS S3 API:
aws s3api put-bucket-lifecycle-configuration \
  --bucket jacobmiller22-secure-backup \
  --lifecycle-configuration file://b2-lifecycle.json
```

---

## 8. Universal Backup Runner Declarative Strategy Engine

The canonical runner image (`tools/backup-runner`) executes one of three declarative strategies controlled via `BACKUP_MODE`:

### 8.1 Strategy Definitions

#### 1. `sqlite-auto` (Default)
Automated non-blocking SQLite database backup for applications that persist data across one or more `.sqlite`, `.sqlite3`, or `.db` files:
- **Recursive DB Discovery**: Scans `${BACKUP_SOURCE_DIR}` for database files.
- **Transactional Online Snapshot**: Calls `sqlite3 <db> ".backup <dest>"` to create clean, checkpointed copies.
- **Companion Asset Staging**: Recursively copies non-database files (`*.blob`, `*.pem`, `*.json`, YAML, configurations) preserving directory structure.
- **Journal File Exclusion**: Automatically ignores SQLite transient write-ahead log and lock files (`*-wal`, `*-shm`, `*-journal`).

#### 2. `filesystem`
Direct directory tree preservation for services storing flat files or append-only document stores:
- **Recursive Tree Copy**: Uses `cp -a` to copy `${BACKUP_SOURCE_DIR}` into staging.
- **Integrity & Attributes**: Preserves POSIX file modes, timestamps, symlinks, and ownership.

#### 3. `hook`
Extensible pre-backup script execution for relational databases and engines requiring dedicated CLI utilities:
- **Hook Contract**: Invokes `${PRE_BACKUP_SCRIPT}` passing the ephemeral staging directory as `$1`.
- **Target Export**: The script places database dumps (e.g. `pg_dump`, `mongodump`, CouchDB exports) directly into `$1`.
- **Automatic Packaging**: Upon exit code `0`, the runner packages, encrypts, and uploads all artifacts produced by the hook.

### 8.2 Environment Variable Specification & Defaults

All backup sidecar parameters are configured declaratively through container environment variables:

| Variable | Canonical / Aliases | Default | Description |
| :--- | :--- | :--- | :--- |
| `BACKUP_MODE` | — | `sqlite-auto` | Declarative strategy: `sqlite-auto`, `filesystem`, or `hook`. |
| `BACKUP_SOURCE_DIR` | — | `/data` | Source directory inside container to snapshot. |
| `SERVICE_NAME` | `BACKUP_TARGET_NAME` | `unknown-service` | Service identifier used in log output, archive naming, and remote prefixes. |
| `BACKUP_PASSPHRASE` | `BACKUP_ENCRYPTION_KEY` | *(Required)* | Master encryption passphrase for OpenSSL PBKDF2 AES-256-CBC. |
| `CRON_SCHEDULE` | `BACKUP_CRON` | `0 16 * * *` | Cron schedule string evaluated in UTC by container crond daemon. |
| `BACKUP_ON_STARTUP` | — | `false` | When `true`, executes an immediate backup run before entering crond loop. |
| `BACKUP_DEST_BUCKET` | `B2_BUCKET_NAME`, `B2_BUCKET`, `RCLONE_B2_BUCKET` | *(Optional)* | Destination Backblaze B2 or S3 bucket name. |
| `BACKUP_DEST_ACCESS_KEY_ID` | `B2_APPLICATION_KEY_ID`, `B2_KEY_ID` | *(Optional)* | Cloud storage Access Key ID / B2 Key ID. |
| `BACKUP_DEST_SECRET_ACCESS_KEY` | `B2_APPLICATION_KEY` | *(Optional)* | Cloud storage Secret Access Key / B2 Application Key. |
| `BACKUP_DEST_ENDPOINT` | — | *(Optional)* | S3 endpoint URL (e.g. `https://s3.us-east-005.backblazeb2.com`). |
| `BACKUP_DEST_PREFIX` | — | `backups/${SERVICE_NAME}` | Prefix path within destination bucket. |
| `B2_DEST_PATH` | — | *(Optional)* | Explicit remote destination path (e.g. `b2:my-bucket/backups/actual`). |
| `PRE_BACKUP_SCRIPT` | `BACKUP_PRE_HOOK`, `HOOK_SCRIPT` | `/hooks/pre-backup.sh` | Hook script path executed when `BACKUP_MODE=hook`. |
| `DISCORD_WEBHOOK_URL` | — | *(Optional)* | Discord webhook URL for failure alert embeds. |
| `HEALTHCHECK_PING_URL` | `HEALTHCHECKS_URL` | *(Optional)* | Healthchecks.io / Dead Man's Snitch ping URL on verified upload success. |

---

## 9. Frictionless Service Enrollment Workflow

Enrolling a new service requires zero code development—simply add a sidecar service definition to the stack's `compose.yml` in **under 15 lines of YAML**:

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

### Volume Mounting Rules:
- **Strict Read-Only Enforcement (`:ro`)**: Application data must always be mounted with `:ro` to prevent the backup runner from ever modifying or locking production storage.
- **Resource Limits**: In production, sidecars specify `mem_limit: 256m` and `cpus: 0.50` to guarantee backups never starve host or application workloads.
