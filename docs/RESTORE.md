# Disaster Recovery & Cold-Storage Restoration Runbook (`RESTORE.md`)

This runbook provides complete, self-contained procedures for restoring any service from cold-storage encrypted backups. 

> [!IMPORTANT]
> **Zero-Dependency Guarantee**: Decrypting these backups requires **only standard OpenSSL and tar**, which are installed by default on all macOS, Linux, BSD, and Windows WSL machines. No custom binaries, Go toolchains, or third-party tools are required.

---

## 1. Security & The Fireproof Wallet Model

All backup archives are encrypted using standard OpenSSL with a master secret passphrase.

1. **Locating the Passphrase**: Open your home fireproof/waterproof document safe. Locate the physical backup card labeled:
   `Self-Hosted Infrastructure Backup Passphrase`
2. **Setting the Environment Variable**: For security during restore sessions, export the passphrase into your shell environment rather than pasting it into terminal command history:
   ```bash
   read -s -p "Enter Backup Passphrase: " BACKUP_PASSPHRASE
   export BACKUP_PASSPHRASE
   echo ""
   ```

---

## 2. Decrypting Archives from Cold Storage

### 2.1 Downloading Archives from Backblaze B2
Download the desired archive from the B2 console, Backblaze CLI, or AWS CLI:
```bash
# Example using aws-cli configured for Backblaze B2
aws s3 cp s3://jacobmiller22-secure-backup/backups/actual/<archive-name>.tar.gz.enc . \
  --endpoint-url https://s3.us-east-005.backblazeb2.com
```

### 2.2 Decrypting and Extracting the Archive
To extract directly into a destination folder (`./extracted`):
```bash
mkdir -p ./extracted

openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in <archive-name>.tar.gz.enc \
  -pass env:BACKUP_PASSPHRASE | \
  tar -xz -C ./extracted
```

### 2.3 Automated Database & Storage Integrity Verification
Before restoring any decrypted backup payload into production volumes, validate internal page consistency, relational foreign key constraints, cryptographic keys, and record counts using the automated verification suite:

```bash
# Auto-detect and verify all services in the extracted payload directory
./tools/backup-dr/verify-db-integrity.sh --dir ./extracted --verbose

# Or verify a specific service (actual, vaultwarden, homeassistant, npm, postgres)
./tools/backup-dr/verify-db-integrity.sh --service vaultwarden --dir ./extracted

# Verify a standalone database or dump file
./tools/backup-dr/verify-db-integrity.sh --file ./extracted/db.sqlite3
```
Exit code `0` confirms the backup is sound and ready for restoration.


---

## 3. Service-Specific Restoration Procedures

### 3.1 Actual Budget (`actual_server`)

#### Backup Contents
The decrypted archive contains:
- `server-files/account.sqlite` (User accounts and metadata)
- `user-files/*.sqlite` (Budget databases per user)
- `user-files/*.blob` (Encrypted client-side budget sync blobs)

#### Recovery Procedure
1. **Stop the Actual Budget container** to ensure no file locks or active WAL journals:
   ```bash
   ssh bjorn "docker stop actual_server-g8woog40sgkcogwkcksgwwoc"
   ```
2. **Identify Docker Volume Path**:
   ```bash
   VOLUME_DIR=$(ssh bjorn "docker volume inspect g8woog40sgkcogwkcksgwwoc_actual-data --format '{{.Mountpoint}}'")
   ```
3. **Copy Restored Files into Volume**:
   ```bash
   # Upload extracted files to staging
   scp -r ./extracted/* bjorn:/tmp/actual-restore-staging/
   
   # Synchronize into volume directory
   ssh bjorn "sudo cp -r /tmp/actual-restore-staging/* $VOLUME_DIR/ && sudo rm -rf /tmp/actual-restore-staging"
   ```
4. **Fix File Permissions (CRITICAL QUIRK)**:
   Actual Budget runs as UID/GID `1000:1000`. If files are owned by `root`, the container will crash on launch:
   ```bash
   ssh bjorn "sudo chown -R 1000:1000 $VOLUME_DIR"
   ```
5. **Restart Container**:
   ```bash
   ssh bjorn "docker start actual_server-g8woog40sgkcogwkcksgwwoc"
   ```
6. **Verify Health**:
   ```bash
   ssh bjorn "docker logs --tail 50 actual_server-g8woog40sgkcogwkcksgwwoc"
   curl -I https://budget.cloud.jacobmiller22.com
   ```

---

### 3.2 Vaultwarden (`vaultwarden`)

#### Backup Contents
The decrypted archive contains:
- `db.sqlite3` (Bitwarden vault entries, ciphers, users, organizations)
- `rsa_key.pem` and `rsa_key.pub` (JWT and API signing keys)
- `attachments/` (User file attachments)
- `sends/` (Bitwarden Send encrypted items)
- `config.json` (Custom server configuration, if present)

#### Recovery Procedure
1. **Stop Vaultwarden**:
   ```bash
   ssh bjorn "docker stop vaultwarden-i0k8s00c48gg4o48ks08o8wk"
   ```
2. **Identify Docker Volume Path**:
   ```bash
   VOLUME_DIR=$(ssh bjorn "docker volume inspect i0k8s00c48gg4o48ks08o8wk_vw-data --format '{{.Mountpoint}}'")
   ```
3. **Copy Restored Files into Volume**:
   ```bash
   scp -r ./extracted/* bjorn:/tmp/vw-restore-staging/
   ssh bjorn "sudo cp -r /tmp/vw-restore-staging/* $VOLUME_DIR/ && sudo rm -rf /tmp/vw-restore-staging"
   ```
4. **Fix File Permissions (CRITICAL QUIRK)**:
   Vaultwarden requires ownership by the vaultwarden user (or root depending on container user mode):
   ```bash
   ssh bjorn "sudo chmod 600 $VOLUME_DIR/rsa_key.pem && sudo chmod 644 $VOLUME_DIR/db.sqlite3"
   ```
5. **Restart Container**:
   ```bash
   ssh bjorn "docker start vaultwarden-i0k8s00c48gg4o48ks08o8wk"
   ```
6. **Verify Vault Decryption**:
   Log into `https://vw.cloud.jacobmiller22.com` on desktop or mobile app to confirm vault items and attachments unlock normally.

---

### 3.3 Home Assistant (`homeassistant`)

#### Backup Contents
The decrypted archive contains:
- `configuration.yaml`, `secrets.yaml`, `automations.yaml`
- `.storage/` (Device registries, entity configs, user tokens, Lovelace dashboards)
- `home-assistant_v2.db` (State history SQLite database)

#### Recovery Procedure
1. **Stop Home Assistant**:
   ```bash
   ssh bjorn "docker stop homeassistant-v8sk04sgss48gwsgcs0kggoo"
   ```
2. **Locate Host Config Bind Mount**:
   Home Assistant config on `bjorn` is located at:
   `/data/coolify/applications/v8sk04sgss48gwsgcs0kggoo/config`
3. **Restore Directory**:
   ```bash
   scp -r ./extracted/* bjorn:/tmp/ha-restore-staging/
   ssh bjorn "sudo cp -r /tmp/ha-restore-staging/* /data/coolify/applications/v8sk04sgss48gwsgcs0kggoo/config/ && sudo rm -rf /tmp/ha-restore-staging"
   ```
4. **Start Container**:
   ```bash
   ssh bjorn "docker start homeassistant-v8sk04sgss48gwsgcs0kggoo"
   ```
5. **Verify Entities**:
   Check `https://ha.cloud.jacobmiller22.com` and inspect Developer Tools -> Logs.

---

### 3.4 Nginx Proxy Manager (`nginx-proxy-manager`)

#### Backup Contents
The decrypted archive contains:
- `database.sqlite` (All proxy hosts, SSL cert assignments, access lists)
- `keys.json` (Encryption keys for NPM credentials)
- `letsencrypt/` (All issued Let's Encrypt certificates and account keys)

#### Recovery Procedure
1. **Stop Nginx Proxy Manager**:
   ```bash
   ssh bjorn "docker stop nginx-proxy-manager-low8ws4g0880kwk0gkwwwow4-215348988738"
   ```
2. **Restore Files to Bind Mounts**:
   - Data folder: `/data/coolify/applications/low8ws4g0880kwk0gkwwwow4/data`
   - Cert folder: `/data/coolify/applications/low8ws4g0880kwk0gkwwwow4/letsencrypt`
   ```bash
   ssh bjorn "sudo cp -r /tmp/npm-restore/data/* /data/coolify/applications/low8ws4g0880kwk0gkwwwow4/data/"
   ssh bjorn "sudo cp -r /tmp/npm-restore/letsencrypt/* /data/coolify/applications/low8ws4g0880kwk0gkwwwow4/letsencrypt/"
   ```
3. **Start Container & Verify Routing**:
   ```bash
   ssh bjorn "docker start nginx-proxy-manager-low8ws4g0880kwk0gkwwwow4-215348988738"
   ```

---

### 3.5 Obsidian CouchDB LiveSync (`obsidian`)

#### Backup Contents
The decrypted archive contains:
- `*.couch` (CouchDB databases including note documents, LiveSync metadata, and design docs)
- `_users.couch`, `_replicator.couch`, `_global_changes.couch` (CouchDB system databases)
- `.shards/` (Database shards and partitioned document stores)
- View index caches and compaction records

#### Recovery Procedure
1. **Stop Obsidian CouchDB Container**:
   Stop `livesync-db` to prevent write contention during directory restoration:
   ```bash
   ssh bjorn "docker stop livesync-db"
   ```
2. **Locate Data Bind Mount**:
   Obsidian CouchDB mounts host directory `./db/data` to `/opt/couchdb/data`:
   ```bash
   DATA_DIR="/Users/jacobmiller22/projects/selfhosted/obsidian/db/data"
   # Or production Coolify application persistent directory on bjorn
   ```
3. **Unpack & Decrypt Encrypted Archive**:
   Download the archive from Backblaze B2 and decrypt using standard OpenSSL into a clean staging folder:
   ```bash
   mkdir -p ./extracted-obsidian
   openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
     -in obsidian-backup-<timestamp>.tar.gz.enc \
     -pass env:BACKUP_PASSPHRASE | \
     tar -xz -C ./extracted-obsidian
   ```
4. **Copy Restored Files into Host Data Directory**:
   ```bash
   # Upload extracted files to bjorn staging
   scp -r ./extracted-obsidian/* bjorn:/tmp/obsidian-restore-staging/

   # Synchronize into target bind mount
   ssh bjorn "sudo cp -r /tmp/obsidian-restore-staging/* $DATA_DIR/ && sudo rm -rf /tmp/obsidian-restore-staging"
   ```
5. **Fix File Permissions (CRITICAL QUIRK)**:
   CouchDB executes internally as user `couchdb` (UID `5984`, GID `5984`). If files are owned by `root`, CouchDB fails to open database files and crashes:
   ```bash
   ssh bjorn "sudo chown -R 5984:5984 $DATA_DIR && sudo chmod -R 0750 $DATA_DIR"
   ```
6. **Restart Container**:
   ```bash
   ssh bjorn "docker start livesync-db"
   ```
7. **Verify Health & Sync Availability**:
   Verify container logs and query the HTTP API endpoint:
   ```bash
   ssh bjorn "docker logs --tail 50 livesync-db"
   ssh bjorn "curl -fsS http://localhost:5984/"
   curl -I https://obsidian.cloud.jacobmiller22.com
   ```
   Open Obsidian on client devices and trigger LiveSync to confirm note replication resumes without conflict.

---

## 4. Disaster Recovery Testing Checklist

Quarterly, perform a dry-run restoration on a non-production machine:
- [ ] Download latest archive from B2 bucket.
- [ ] Decrypt using offline passphrase from fireproof safe.
- [ ] Inspect SQLite integrity: `sqlite3 <extracted_db> "PRAGMA integrity_check;"` -> Output must be `ok`.
- [ ] Verify tar extract contains no 0-byte corrupted files.
