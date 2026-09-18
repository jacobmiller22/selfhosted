# Obsidian LiveSync Directives (`obsidian/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `obsidian/compose.yml`  
> **Ingress Domain**: `https://obsidian.cloud.jacobmiller22.com`  
> **Internal Port**: `5984:5984`

---

## 1. Architecture Overview

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine).
- **Service**: Apache CouchDB 3.3.3 container (`livesync-db`).
- **Role**: Backend document store for the Obsidian Self-hosted LiveSync plugin, synchronizing markdown notes across mobile and desktop clients.
- **Networks**: `nginx-proxy-manager` external bridge network.
- **Storage**: Bind mount `./db/data` mounted to `/opt/couchdb/data`.

---

## 2. Remote Host Verification Protocol for `obsidian/`

All management actions run remotely on `bjorn`:

```bash
# Verify host reachability
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"

# Check container status
ssh bjorn "docker ps --filter name=livesync-db"

# Inspect CouchDB logs
ssh bjorn "docker logs --tail 100 livesync-db"

# Restart container
ssh bjorn "docker restart livesync-db"

# Query CouchDB status
ssh bjorn "curl -fsS http://localhost:5984/"
```

---

## 3. Storage & Secret Hygiene

- **Password Protection**: Passwords (`COUCHDB_PASSWORD`) must be injected via environment variables; never commit plain text passwords to `obsidian/compose.yml`.
- **Data Persistence**: `./db/data` contains the raw CouchDB transaction files. Never delete this directory during maintenance.
