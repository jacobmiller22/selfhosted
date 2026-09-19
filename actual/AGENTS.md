# Actual Budget & Auto-Categorizer Directives (`actual/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `actual/compose.yml`  
> **Ingress Domain**: `https://budget.cloud.jacobmiller22.com`

---

## 1. Architecture Overview

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine managed via Coolify).
- **Network**: `nginx-proxy-manager` external bridge network.
- **Containers**:
  1. `actual_server`: Official Actual Budget server container (`docker.io/actualbudget/actual-server:26.9.0`), listening internally on port `5006`.
  2. `actual-backup`: Automated SQLite backup runner container performing non-blocking snapshots to Backblaze B2.
  3. `actual-auto-categorizer`: TypeScript ML sidecar daemon listening on host port `3080:3080` to classify bank transactions via local ONNX models.
  4. `actual-server-staging`: Ephemeral staging container (`profiles: ["staging"]`, host port `5006`, memory limit `256m`, cpu `0.50`, volume `actual-stage-data`).
- **Persistent Storage**:
  - Production volume: `actual-data` mounted at `/data/` in `actual_server`.
  - Staging volume: `actual-stage-data` mounted at `/data` in `actual-server-staging`.
  - Database files: `/data/server-files/account.sqlite`, `/data/user-files/*.sqlite`, and sync blobs `/data/user-files/*.blob`.

---

## 2. Remote Host Verification Protocol for `actual/`

Before issuing any command, confirm reachability on `bjorn`:
```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"
```

### Canonical Remote Commands

```bash
# Check container status
ssh bjorn "docker ps --filter name=actual"

# View Actual Budget server logs
ssh bjorn "docker logs --tail 100 actual-actual_server-1" # or Coolify container hash name

# View Auto-Categorizer logs
ssh bjorn "docker logs --tail 100 actual-auto-categorizer"

# Restart Actual stack
ssh bjorn "docker restart actual-auto-categorizer"
```

---

## 3. Auto-Categorizer ML Sidecar Operations

The auto-categorizer runs a Node.js/TypeScript daemon on port `3080`.

### Health & Sync Query Patterns
Containers may not have `curl` installed; execute commands via `node -e fetch` inside the container:
```bash
# Health check
ssh bjorn "docker exec actual-auto-categorizer node -e '
fetch(\"http://localhost:3080/health\").then(r => r.json()).then(console.log).catch(console.error);
'"

# Trigger manual transaction sync
ssh bjorn "docker exec actual-auto-categorizer node -e '
fetch(\"http://localhost:3080/api/sync\", { method: \"POST\" }).then(r => r.json()).then(console.log).catch(console.error);
'"

# Check analytics snapshot status
ssh bjorn "docker exec actual-auto-categorizer node -e '
fetch(\"http://localhost:3080/api/export\").then(r => r.json()).then(console.log).catch(console.error);
'"

# Trigger on-demand analytics snapshot export
ssh bjorn "docker exec actual-auto-categorizer node -e '
fetch(\"http://localhost:3080/api/export\", { method: \"POST\" }).then(r => r.json()).then(console.log).catch(console.error);
'"
```

### Hot-Patching Workflow (Fast Verification)
To test TypeScript changes or updated ONNX models without waiting for full Coolify git builds:
```bash
# 1. Compile TypeScript locally in worktree
npm run build --prefix actual/tools/auto-categorizer

# 2. Stage compiled dist on bjorn
scp -r actual/tools/auto-categorizer/dist/* bjorn:/tmp/auto-categorizer-dist/
ssh bjorn "docker cp /tmp/auto-categorizer-dist/. actual-auto-categorizer:/app/dist/"

# 3. Upload ONNX models if modified
scp -r actual/auto-categorizer-models/* bjorn:/tmp/auto-categorizer-models/
ssh bjorn "docker cp /tmp/auto-categorizer-models/. actual-auto-categorizer:/app/src/models/"

# 4. Restart container
ssh bjorn "docker restart actual-auto-categorizer"
```

---

## 4. SQLite Safety & Backup Rules

- **NEVER use raw `cp`** on active SQLite databases (`account.sqlite`, user files) during runtime.
- **Safe Snapshot Command**:
  ```bash
  sqlite3 /data/server-files/account.sqlite ".backup /tmp/account-backup.sqlite"
  ```
- **File Ownership**: Actual Budget runs as UID/GID `1000:1000`. Restored files must retain `chown -R 1000:1000 /data`.
- **Passphrase Protection**: Backups are encrypted with OpenSSL AES-256-CBC PBKDF2 using `BACKUP_PASSPHRASE` injected via Coolify environment variables.
