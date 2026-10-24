# `btcupdown` Service Directives (`btcupdown/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `btcupdown/compose.yml`  
> **Public Endpoint**: `https://btcupdown.cloud.jacobmiller22.com`  
> **Internal Container Ports**: `8080` (`Host Port: 8085` — Data Broker), `8081` (`Host Port: 8086` — Co-Located Engine Control API)  
> **Source Repository**: `https://github.com/jacobmiller22/btcupdown`

---

## 1. Architecture Overview (Co-Located Data Broker + Attached Engine Daemon)

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine + Coolify).
- **Container**: `btcupdown` (single-container Rust runtime built from `jacobmiller22/btcupdown`).
- **Supervised Processes** (`entrypoint.sh`):
  1. **`data-broker`**: Central Axum WebSocket & REST broker listening on `0.0.0.0:8080`, persisting SQLite WAL state in `/data/broker.sqlite` (`BROKER_RAW_RETENTION_DAYS=0`).
  2. **`btcupdown-engine`** (`engine-daemon`): Co-located policy engine daemon listening on `0.0.0.0:8081` (host `8086`), consuming `ws://127.0.0.1:8080/ws`, evaluating 18 fee-aware strategies (`VenueFeeModel`) and BYOC `ActionSink`s, streaming local participant telemetry (`ENGINE_PARTICIPANT_ID=bjorn`) to `ws://127.0.0.1:8080/ws/telemetry`, and **sharing the broker's SQLite WAL database** (`/data/broker.sqlite` with `INSERT OR IGNORE INTO raw_events` and disjoint `EngineStore` tables/views).
  3. **`vixxy-poller`**: Polls `GET /api/vixy/15m/current` every ~3000ms (±250ms jitter), renews the `vixy_session` JWT every 30s via `POST /api/auth/heartbeat`, persists rotated tokens atomically to `/data/vixxy_token_state.json`, and streams events over `ws://127.0.0.1:8080/ws/ingest`.
  4. **`kalshi-poller`**: Discovers active `KXBTC15M` 15-minute contracts via the Kalshi Public API, polls real-time YES/NO bid/ask quotes and final settlement statuses, and streams `kalshi.15m.market` events into `data-broker` over `ws://127.0.0.1:8080/ws/ingest`.
- **Installed Binaries**:
  - `/usr/local/bin/data-broker`
  - `/usr/local/bin/btcupdown-engine` (co-located policy engine & BYOC execution daemon)
  - `/usr/local/bin/vixxy-poller`
  - `/usr/local/bin/kalshi-poller`
  - `/usr/local/bin/btcupdown-cli` (operator HTTP control client, BYOC ActionSink controller & offline SQLite backtester)
- **Networks**:
  - `nginx-proxy-manager` (shared bridge network for reverse proxy routing).
- **Persistent Storage**:
  - Named Docker volume `btcupdown-data` mounted at `/data`:
    - `/data/broker.sqlite` (shared WAL database housing both `BrokerStore` tables (`raw_events`, `state_changes`, `cycles`, `strategy_standings`, `strategy_experiments`, `strategy_trades`, `strategy_outputs`) and co-located `EngineStore` tables/views (`experiments`, `strategy_books`, `raw_trades`, `policy_outputs`, `action_sinks`, `action_executions`, `v_strategy_standings`, `v_trade_history`)).
    - `/data/vixxy_token_state.json` (atomically persisted Vixxy session JWT state).
    - `/data/trade_log.txt` (human-readable paper/live trade audit log).
    - `/data/kalshi.env` & `/data/kalshi_private.pem` (`chmod 600` BYOC Kalshi API v2 RSA-PSS credentials sourced at container startup, never stored in Git or SQLite).
- **Live Real-Money Experiment & BYOC Action Sinks (`live-kalshi`)**:
  - Experiment `live-kalshi` runs alongside `default` (paper) with **`$50.00` starting balance per strategy** explicitly allocated to **`wide`** (`$50.00`) and **`full port`** (`$50.00`).
  - Two live `kalshi_live` BYOC action sinks (`dry_run: false`, `max_notional_dollars: 50.0`) are bound strictly to `experiment_id = "live-kalshi"`:
    - `kalshi-live-wide` (`experiment_id="live-kalshi"`, `strategy_name="wide"`)
    - `kalshi-live-full-port` (`experiment_id="live-kalshi"`, `strategy_name="full port"`)

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

# Probe internal Data Broker health, latest snapshot, and telemetry (:8085 -> :8080)
ssh bjorn "curl -fsS http://127.0.0.1:8085/health"
ssh bjorn "curl -fsS http://127.0.0.1:8085/api/latest"
ssh bjorn "curl -fsS http://127.0.0.1:8085/api/telemetry"

# Probe co-located Engine Daemon HTTP Control API (:8086 -> :8081)
ssh bjorn "curl -fsS http://127.0.0.1:8086/health"
ssh bjorn "curl -fsS http://127.0.0.1:8086/api/status"
ssh bjorn "curl -fsS http://127.0.0.1:8086/api/status?experiment=live-kalshi"
ssh bjorn "curl -fsS http://127.0.0.1:8086/api/experiments"
ssh bjorn "curl -fsS http://127.0.0.1:8086/api/actions"

# Operator CLI via HTTP Control API (--engine-url) or Shared SQLite (--db)
ssh bjorn "docker exec btcupdown btcupdown-cli --engine-url http://127.0.0.1:8081 status"
ssh bjorn "docker exec btcupdown btcupdown-cli --engine-url http://127.0.0.1:8081 status --experiment live-kalshi"
ssh bjorn "docker exec btcupdown btcupdown-cli --engine-url http://127.0.0.1:8081 actions"
ssh bjorn "docker exec btcupdown btcupdown-cli --db /data/broker.sqlite status"

# Run deterministic offline backtest directly against shared /data/broker.sqlite
ssh bjorn "docker exec btcupdown btcupdown-cli backtest --db /data/broker.sqlite --id exp-backtest-smoke --strategies baseline,scalp --start-balance 100"

# Safe SQLite snapshot of shared broker.sqlite
ssh bjorn "docker exec btcupdown sqlite3 /data/broker.sqlite '.backup /data/broker-snapshot.sqlite'"
```

---

## 3. Reverse Proxy & Security Boundary (`btcupdown.cloud.jacobmiller22.com`)

- **Nginx Proxy Manager** terminates TLS (`*.cloud.jacobmiller22.com` wildcard certificate) and forwards traffic to `http://btcupdown:8080` (`data-broker`) with **Websockets Support** enabled.
- **Co-Located Engine Daemon Isolation**:
  - `btcupdown-engine` HTTP Control API (`:8081`, host `:8086`) is **never** exposed through Nginx Proxy Manager to the public internet; it is accessible exclusively via local loopback (`127.0.0.1:8086`) or Tailscale (`http://bjorn:8086`).
- **External Write Protection**:
  - `/ws/ingest` and `/api/ingest` are explicitly blocked (`HTTP 403 Forbidden`) at the Nginx Proxy Manager layer so only the internal `vixxy-poller` and `kalshi-poller` processes can ingest market events over loopback (`127.0.0.1:8080`).
  - Publicly accessible streaming & telemetry endpoints:
    - `wss://btcupdown.cloud.jacobmiller22.com/ws` (Push-only live stream: initial `Snapshot` + real-time `Event` ticks)
    - `wss://btcupdown.cloud.jacobmiller22.com/ws/telemetry` (Bidirectional participant strategy telemetry WS stream)
    - `POST https://btcupdown.cloud.jacobmiller22.com/api/telemetry` (REST telemetry ingest)
    - `GET https://btcupdown.cloud.jacobmiller22.com/api/telemetry` (REST telemetry query by participant/strategy/experiment)
    - `GET https://btcupdown.cloud.jacobmiller22.com/api/latest`
    - `GET https://btcupdown.cloud.jacobmiller22.com/api/history`
    - `GET https://btcupdown.cloud.jacobmiller22.com/api/cycles`
    - `GET https://btcupdown.cloud.jacobmiller22.com/health`
