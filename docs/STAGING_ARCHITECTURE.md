# Ephemeral Staging Architecture & Compose Profile Specification

This document defines the architecture, port allocation schema, isolation guarantees, and operational procedures for ephemeral staging environments across the `selfhosted` infrastructure on remote host `bjorn`.

---

## 1. Executive Summary & Design Principles

To adhere to **Axiom 2 (Zero Tolerance for Data Loss)** and **Axiom 3 (Radical Simplicity & Operational Humility)** of homelab governance, staging environments must fulfill four non-negotiable guarantees:

1. **Zero Runtime Overhead When Idle**: Staging services utilize native Docker Compose profiles (`profiles: ["staging"]`). By default, normal `docker compose up -d` invocations start only production workloads. Staging containers remain stopped when inactive, consuming 0% CPU and 0 MB RAM.
2. **Strict Resource Caps**: Every staging container is bound by hard kernel limits (`mem_limit: 256m`, `cpus: 0.50`), guaranteeing that experimental workloads or runaway scripts cannot starve production services.
3. **Complete Data & Network Isolation**: Staging containers write exclusively to isolated staging volumes (`actual-stage-data`, `vw-stage-data`) and communicate across an isolated bridge network (`staging-net`). Production databases and ingress networks are inaccessible from staging.
4. **Deterministic Port Schema**: Non-conflicting static host ports are assigned to staging services, avoiding collisions with production reverse proxies and internal routing.

---

## 2. Staging Port & Service Allocation Schema

| Service | Staging Container Name | Staging Host Port | Container Port | Production Host Port / Ingress | Resource Cap (RAM / CPU) | Persistent Volume |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Actual Budget** | `actual-server-staging` | **`5006`** | `5006` | Internal NPM routing (`https://budget.cloud.jacobmiller22.com`) | `256m` / `0.50` | `actual-stage-data` (`/data`) |
| **Vaultwarden** | `vaultwarden-staging` | **`7278`** | `80` | Host `7277` (`https://vw.cloud.jacobmiller22.com`) | `256m` / `0.50` | `vw-stage-data` (`/data`) |

---

## 3. Service Declarations & Compose Profile Configuration

Staging containers are declared directly within their respective subsystem Compose files (`actual/compose.yml` and `vaultwarden/compose.yml`) under `profiles: ["staging"]`.

### 3.1 Actual Budget Staging (`actual/compose.yml`)

```yaml
services:
  actual-server-staging:
    image: docker.io/actualbudget/actual-server:26.9.0
    container_name: actual-server-staging
    profiles: ["staging"]
    restart: unless-stopped
    ports:
      - "5006:5006"
    volumes:
      - actual-stage-data:/data
    networks:
      - staging-net
    mem_limit: 256m
    cpus: 0.50

networks:
  staging-net:

volumes:
  actual-stage-data:
```

### 3.2 Vaultwarden Staging (`vaultwarden/compose.yml`)

```yaml
services:
  vaultwarden-staging:
    image: vaultwarden/server:1.35.4
    container_name: vaultwarden-staging
    profiles: ["staging"]
    restart: unless-stopped
    environment:
      DOMAIN: "http://localhost:7278"
      SIGNUPS_ALLOWED: "false"
    volumes:
      - vw-stage-data:/data
    ports:
      - "7278:80"
    networks:
      - staging-net
    mem_limit: 256m
    cpus: 0.50

networks:
  staging-net:

volumes:
  vw-stage-data:
```

---

## 4. Isolation & Security Safeguards

### 4.1 Volume Segregation
- **Production Volumes**: `actual-data` and `vw-data` are mounted by production containers and automated backup runners (`actual-backup`, `vw-backup`).
- **Staging Volumes**: `actual-stage-data` and `vw-stage-data` are dedicated strictly to staging instances.
- **Backup Runner Isolation**: Automated backup runners never mount staging volumes, preventing test artifacts from polluting production Backblaze B2 snapshots.

### 4.2 Network Containment
- Staging containers attach to `staging-net` (an isolated bridge network).
- Production containers attach to `nginx-proxy-manager` for SSL ingress routing.
- This network boundary ensures staging containers cannot intercept production traffic or resolve production internal service names.

### 4.3 Staging Environment Safety Guards
- **Vaultwarden**: `SIGNUPS_ALLOWED: "false"` prevents unauthorized registration during staging tests. `DOMAIN` is bound to `http://localhost:7278`.
- **Actual Budget**: Default authentication protects staging data access; no ingress SSL certificates are provisioned for staging ports.

---

## 5. Operational Procedures & Remote Runbook

All commands execute on remote host `bjorn` via SSH wrappers per the Remote Host Verification Protocol (RHVP).

### 5.1 Syntax Verification
```bash
# Verify base production config (staging omitted)
docker compose -f actual/compose.yml config
docker compose -f vaultwarden/compose.yml config

# Verify staging profile config (staging included)
docker compose -f actual/compose.yml --profile staging config
docker compose -f vaultwarden/compose.yml --profile staging config
```

### 5.2 Launching Staging Containers
```bash
# Start Actual Budget staging container
ssh bjorn "docker compose -f /path/to/actual/compose.yml --profile staging up -d actual-server-staging"

# Start Vaultwarden staging container
ssh bjorn "docker compose -f /path/to/vaultwarden/compose.yml --profile staging up -d vaultwarden-staging"
```

### 5.3 Inspecting Staging Containers
```bash
# Check running status
ssh bjorn "docker ps --filter name=staging"

# Inspect staging container resource consumption
ssh bjorn "docker stats actual-server-staging vaultwarden-staging --no-stream"

# View staging logs
ssh bjorn "docker logs --tail 50 actual-server-staging"
ssh bjorn "docker logs --tail 50 vaultwarden-staging"
```

### 5.4 Stopping & Decommissioning Staging
```bash
# Stop staging containers (retains staging data in volume)
ssh bjorn "docker compose -f /path/to/actual/compose.yml --profile staging stop actual-server-staging"
ssh bjorn "docker compose -f /path/to/vaultwarden/compose.yml --profile staging stop vaultwarden-staging"

# Teardown staging container and destroy ephemeral volume
ssh bjorn "docker compose -f /path/to/actual/compose.yml --profile staging down -v"
```
