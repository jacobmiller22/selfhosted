# `btcupdown` Service Directives (`btcupdown/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `btcupdown/compose.yml`  
> **Public Endpoint**: `https://btcupdown.cloud.jacobmiller22.com`  
> **Internal Container Port**: `8080` (`Host Port: 8085`)  
> **Source Repository**: `https://github.com/jacobmiller22/btcupdown`

---

## 1. Architecture Overview

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine + Coolify).
- **Container**: `btcupdown` (single-container Rust runtime built from `jacobmiller22/btcupdown`).
- **Supervised Processes** (`entrypoint.sh`):
  1. **`data-broker`**: Central Axum WebSocket & REST broker listening on `0.0.0.0:8080`, persisting SQLite WAL state in `/data/broker.sqlite` (`BROKER_RAW_RETENTION_DAYS=0`).
  2. **`vixxy-poller`**: Polls `GET /api/vixy/15m/current` every ~3000ms (±250ms jitter), renews the `vixy_session` JWT every 30s via `POST /api/auth/heartbeat`, persists rotated tokens atomically to `/data/vixxy_token_state.json`, and streams events over `ws://127.0.0.1:8080/ws/ingest`.
  3. **`kalshi-poller`**: Discovers active `KXBTC15M` 15-minute contracts via the Kalshi Public API, polls real-time YES/NO bid/ask quotes and final settlement statuses, and streams `kalshi.15m.market` events into `data-broker` over `ws://127.0.0.1:8080/ws/ingest`.
- **Installed Binaries**:
  - `/usr/local/bin/data-broker`
  - `/usr/local/bin/vixxy-poller`
  - `/usr/local/bin/kalshi-poller`
  - `/usr/local/bin/btcupdown-cli` (paper-trading engine monitor)
- **Networks**:
  - `nginx-proxy-manager` (shared bridge network for reverse proxy routing).
- **Persistent Storage**:
  - Named Docker volume `btcupdown-data` mounted at `/data` (`broker.sqlite` and `vixxy_token_state.json`).

---

## 2. Remote Host Verification Protocol for `btcupdown/`

All runtime inspections and administrative commands execute on `bjorn` over SSH:

```bash
# Verify host reachability
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"

# Check container status and health
ssh bjorn "docker ps --filter name=btcupdown"

# View container logs
ssh bjorn "docker logs --tail 100 btcupdown"

# Check active Vixxy session token status & expiration
ssh bjorn "docker exec btcupdown vixxy-poller auth status"
ssh bjorn "docker exec btcupdown vixxy-poller auth status --json"

# Probe internal healthz and latest snapshot
ssh bjorn "curl -fsS http://127.0.0.1:8085/healthz"
ssh bjorn "curl -fsS http://127.0.0.1:8085/api/latest"

# Safe SQLite snapshot of broker.sqlite
ssh bjorn "docker exec btcupdown sqlite3 /data/broker.sqlite '.backup /data/broker-snapshot.sqlite'"
```

---

## 3. Reverse Proxy & Security Boundary (`btcupdown.cloud.jacobmiller22.com`)

- **Nginx Proxy Manager** terminates TLS (`*.cloud.jacobmiller22.com` wildcard certificate) and forwards traffic to `http://btcupdown:8080` with **Websockets Support** enabled.
- **External Write Protection**:
  - `/ws/ingest` and `/api/ingest` are explicitly blocked (`HTTP 403 Forbidden`) at the Nginx Proxy Manager layer so only the internal `vixxy-poller` process can ingest events over loopback (`127.0.0.1:8080`).
  - Publicly readable endpoints:
    - `wss://btcupdown.cloud.jacobmiller22.com/ws` (Push-only live stream: initial `Snapshot` + real-time `Event` ticks)
    - `GET https://btcupdown.cloud.jacobmiller22.com/api/latest`
    - `GET https://btcupdown.cloud.jacobmiller22.com/api/history`
    - `GET https://btcupdown.cloud.jacobmiller22.com/api/cycles`
    - `GET https://btcupdown.cloud.jacobmiller22.com/healthz`
