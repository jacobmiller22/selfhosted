# Nginx Proxy Manager Directives (`nginx-proxy-manager/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `nginx-proxy-manager/compose.yml`  
> **Admin Web UI**: `http://bjorn:81` (via Tailscale or LAN)  
> **Public Ports**: `80` (HTTP), `443` (HTTPS)

---

## 1. Architecture Overview

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine).
- **Container**: `nginx-proxy-manager` (`jc21/nginx-proxy-manager:latest`).
- **Host Port Bindings**:
  - `80:80` (Public HTTP Ingress)
  - `443:443` (Public HTTPS Ingress)
  - `81:81` (Admin Web Console)
  - `8096:8096` (Optional media/stream port)
- **Networks**:
  - `nginx-proxy-manager` (internal bridge network shared by proxy targets)
  - `coolify` (external Coolify overlay network)
- **Persistent Storage**:
  - `./data` mounted to `/data` in container (contains `database.sqlite` and `keys.json`).
  - `./letsencrypt` mounted to `/etc/letsencrypt` in container (stores all SSL certificates and account keys).

---

## 2. Remote Host Verification Protocol for `nginx-proxy-manager/`

All management actions run remotely on `bjorn`:

```bash
# Verify host reachability
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"

# Check container status
ssh bjorn "docker ps --filter name=nginx-proxy-manager"

# Inspect Nginx Proxy Manager logs
ssh bjorn "docker logs --tail 100 nginx-proxy-manager"

# Test Nginx syntax inside container
ssh bjorn "docker exec nginx-proxy-manager nginx -t"

# Reload Nginx configuration without restarting container
ssh bjorn "docker exec nginx-proxy-manager nginx -s reload"

# Check Admin UI availability on host
ssh bjorn "curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:81"
```

---

## 3. Operational Standards & Configuration Rules

### 3.1 Reverse Proxy Routing
- **Internal Host Targets**:
  - For services running in the `nginx-proxy-manager` Docker network (e.g., `actual_server`, `vaultwarden`, `livesync-db`), forward using the container name and container port (e.g. `actual_server:5006`).
  - For services running with `network_mode: host` (e.g. `homeassistant`), forward to `172.17.0.1` (Docker bridge gateway) or `bjorn`'s LAN IP with port `8123`.

### 3.2 WebSocket Support
- Always enable **Websockets Support** toggle in the NPM UI for real-time services (`homeassistant`, `vaultwarden`, `actual`).

### 3.3 Let's Encrypt Certificate Safeguards
- Certificates and ACME account credentials reside in `/etc/letsencrypt`.
- **Preserve Certificate Storage**: Never delete or recreate `./letsencrypt` during routine maintenance. Let's Encrypt enforces strict weekly rate limits (5 duplicate certificates per week per domain set).
- When restoring from backup, restore `/etc/letsencrypt` before spinning up the container.

### 3.4 SQLite Database Backups
- NPM stores all proxy hosts, access lists, and user accounts in `/data/database.sqlite`.
- Take safe snapshots with:
  ```bash
  ssh bjorn "sqlite3 /data/database.sqlite '.backup /tmp/npm-backup.sqlite'"
  ```
