# Vaultwarden Directives (`vaultwarden/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `vaultwarden/compose.yml`  
> **Ingress Domain**: `https://vw.cloud.jacobmiller22.com`  
> **Internal Host Port**: `7277` (mapped to container port `80`)

---

## 1. Architecture Overview

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine).
- **Network**: `nginx-proxy-manager` external bridge network.
- **Containers**:
  1. `vaultwarden`: Bitwarden-compatible lightweight server (`vaultwarden/server:1.35.4`), exposing port `7277:80`.
  2. `vw-backup`: Automated SQLite backup runner container performing non-blocking snapshots to Backblaze B2.
  3. `vaultwarden-staging`: Ephemeral staging container (`profiles: ["staging"]`, host port `7278:80`, memory limit `256m`, cpu `0.50`, volume `vw-stage-data`).
- **Persistent Storage**:
  - Production volume: `vw-data` mounted at `/data/` in `vaultwarden`.
  - Staging volume: `vw-stage-data` mounted at `/data` in `vaultwarden-staging`.
  - Core files in `/data/`:
    - `db.sqlite3`: Main user and vault credential database.
    - `rsa_key.pem` & `rsa_key.pub`: Master server JWT signing keys.
    - `attachments/` & `sends/`: Encrypted file attachments and Bitwarden Send objects.
    - `config.json`: Server administrative configuration.

---

## 2. Remote Host Verification Protocol for `vaultwarden/`

All management actions run remotely on `bjorn`:

```bash
# Verify host reachability
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"

# Check Vaultwarden containers
ssh bjorn "docker ps --filter name=vaultwarden"

# Inspect live logs
ssh bjorn "docker logs --tail 100 vaultwarden"

# Restart Vaultwarden container
ssh bjorn "docker restart vaultwarden"

# Query local HTTP health on bjorn
ssh bjorn "curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:7277/alive"
```

---

## 3. Critical Security & Storage Safeguards

### 3.1 SQLite Locking Precautions
- **NEVER use raw `cp`** or tar on `db.sqlite3` while the Vaultwarden container is actively writing transactions.
- Always use SQLite's native online backup API:
  ```bash
  ssh bjorn "docker run --rm -v vw-data:/data alpine sh -c 'apk add --no-cache sqlite && sqlite3 /data/db.sqlite3 \".backup /tmp/backup.sqlite3\"'"
  ```

### 3.2 RSA Key Permissions (`600`)
- The server private key `/data/rsa_key.pem` MUST have strict `600` permissions (read/write by container owner only).
- When restoring from a backup archive:
  ```bash
  chmod 600 /data/rsa_key.pem
  chmod 644 /data/rsa_key.pub
  ```
- **Key Loss Consequence**: Restoring `db.sqlite3` without its corresponding `rsa_key.pem` invalidates all client authentication sessions and requires global password vault re-logins.

### 3.3 Read-Only Backup Mounts
- In `vaultwarden/compose.yml`, backup containers must mount volume storage as read-only:
  ```yaml
  volumes:
    - vw-data:/tmp/vw-data:ro
  ```
- Prevents backup jobs from modifying or corrupting primary vault storage during archive execution.

### 3.4 Ingress & WebSockets
- Vaultwarden supports live sync notifications via WebSockets on port `3012` (or built-in rocket routes in modern versions). Ensure NPM routes traffic properly with WebSocket upgrade headers enabled.
