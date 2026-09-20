# Self-Hosted Backup Architecture & Disaster Recovery Specification

This document details the architectural design, security model, alerting protocols, and service inventories for all self-hosted infrastructure running on host server **`bjorn`**.

---

## 1. Executive Summary & Problem Statement

The self-hosted infrastructure hosts critical services including financial management (**Actual Budget**), credentials and passwords (**Vaultwarden**), home automation (**Home Assistant**), and reverse proxy routing with SSL termination (**Nginx Proxy Manager**), all coordinated through **Coolify**.

### Legacy Shortcomings (`volback`):
1. **Single-Point Overwrite**: Backups wrote to a fixed, static object key (`backups/actual/data-backup.zip.enc` and `backups/vw/vw-db-backup.sqlite3.enc`), destroying previous recovery points daily.
2. **Proprietary Encryption Format**: Backups relied on `volback` (a custom Go tool using Argon2id with custom binary framing + AES-128-CTR). Recovery in an emergency required compiling custom Go binaries.
3. **Silent Failures**: Shell scripts lacked `set -euo pipefail` and error traps. If backups failed, the container exited 0 and no alerts were triggered.
4. **Live SQLite Inconsistency**: Backups of Actual Budget copied live SQLite databases via raw `cp -r` during active writes.
5. **Coverage Gaps**: Home Assistant, Nginx Proxy Manager, and Coolify's PostgreSQL database had no automated backups.

---

## 2. Target Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│ Host Server: bjorn (Docker & Coolify Engine)                           │
│                                                                        │
│  ┌───────────────────────┐         ┌────────────────────────────────┐  │
│  │ Application Volumes   │         │ Universal Backup Runner        │  │
│  │  - Actual Budget      │────────▶│  (Alpine, ~45MB)               │  │
│  │  - Vaultwarden        │         │  1. Safe SQLite .backup / VACUUM│  │
│  │  - Home Assistant     │         │  2. Tar + OpenSSL AES-256-CBC  │  │
│  │  - Nginx Proxy Manager│         │  3. Timestamped B2/S3 Upload   │  │
│  │  - Obsidian CouchDB   │         │  4. Trap ERR ──▶ Discord Alert │  │
│  │  - Coolify DB         │         │  5. On Success ──▶ Snitch Ping │  │
│  └───────────────────────┘         │                                │  │
│                                    └────────────────────────────────┘  │
└────────────────────────────────────────────────────┬───────────────────┘
                                                     │ TLS / S3 API
                                                     ▼
                                    ┌────────────────────────────────┐
                                    │ Backblaze B2 (Cloud Storage)   │
                                    │  - Bucket: secure-backup       │
                                    │  - Non-destructive timestamps  │
                                    │  - 30-day lifecycle retention  │
                                    └────────────────────────────────┘
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
