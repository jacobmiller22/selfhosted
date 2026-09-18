# Self-Hosted Monitoring Infrastructure

This directory contains the production Docker Compose stack and provisioning configuration for the unified monitoring system on host server **`bjorn`**.

For the exhaustive architectural specification, benchmark comparison, storage retention math, and cgroups v2 compatibility details, see [docs/MONITORING_ARCHITECTURE.md](../docs/MONITORING_ARCHITECTURE.md).

---

## 1. Stack Components

- **VictoriaMetrics** (`victoriametrics/victoria-metrics:v1.99.0`):
  Ultra-efficient, Prometheus-compatible time-series database. Configured for **90-day retention** and **< 128MB RAM**.
- **cAdvisor** (`gcr.io/cadvisor/cadvisor:v0.49.1`):
  Docker container resource attribution via Linux cgroups v2. Configured with a 15-second housekeeping interval and stripped non-essential metrics for **< 80MB RAM**.
- **Node Exporter** (`quay.io/prometheus/node-exporter:v1.8.1`):
  Linux host hardware and OS telemetry exporter (CPU, RAM, disk capacity on `/` and `/var/lib/docker`, network interfaces) consuming **< 30MB RAM**.
- **Grafana** (`grafana/grafana:11.2.0`):
  Observability dashboard UI with automated file-based datasource and dashboard provisioning consuming **< 120MB RAM**.

---

## 2. Directory Layout

```
monitoring/
├── compose.yml                               # Docker Compose definition with hard resource bounds
├── README.md                                 # Operational runbook and deployment documentation
├── victoriametrics/
│   └── prometheus.yml                        # Scrape configuration for Node Exporter, cAdvisor, VM
└── grafana/
    ├── provisioning/
    │   │   ├── datasources.yml               # Automated VictoriaMetrics Prometheus datasource
    │   │   └── victoriametrics.yml           # Secondary VictoriaMetrics datasource alias
    │   ├── dashboards/
    │   │   └── dashboards.yml                # File provider mapping for JSON dashboards
    │   └── alerting/
    │       └── alerting.yaml                 # Unified alert rules, contact points & notification policy
    └── dashboards/
        ├── README.md                         # Dashboard templates, JSON definitions, and IDs
        ├── host-metrics.json                 # Host overview & capacity dashboard (UID: host-overview)
        └── container-metrics.json            # Container telemetry leaderboard (UID: container-telemetry)
```

---

## 3. Network & Security Architecture

1. **Dual Network Isolation**:
   - `monitoring`: Internal Docker bridge network. Scrapes occur over internal DNS (`cadvisor:8080`, `victoria-metrics:8428`).
   - `nginx-proxy-manager`: External Docker network. **Only Grafana joins this network** to expose its UI to Nginx Proxy Manager.
2. **Port Bindings**:
   - VictoriaMetrics: `8428:8428` (TSDB ingestion and PromQL query API).
   - Node Exporter: `9100` (host network mode).
   - cAdvisor: `8080:8080` (bridge network port mapping).
   - **Zero ports are bound to `0.0.0.0` or exposed publicly.**
   - External access is routed through Nginx Proxy Manager via SSL to Grafana (`https://monitoring.cloud.jacobmiller22.com`).

---

## 4. Resource Bounds (< 360MB RAM Steady-State)

Every container enforces strict hard resource limits in `compose.yml`:

| Container | Hard RAM Limit | RAM Reservation | Hard CPU Limit | Steady-State RAM |
| :--- | :--- | :--- | :--- | :--- |
| `victoria-metrics` | 128MB | 64MB | 0.25 CPU | ~35MB |
| `cadvisor` | 80MB | 40MB | 0.20 CPU | ~35MB |
| `node-exporter` | 30MB | 15MB | 0.10 CPU | ~15MB |
| `grafana` | 120MB | 60MB | 0.25 CPU | ~50MB |
| **Total Stack** | **358MB Hard Ceiling** | **179MB** | **0.80 CPU** | **~135MB** |

---

## 5. Operations & Health Verification

### Starting the Stack:
```bash
docker compose -f monitoring/compose.yml up -d
```

### Checking Container Health & Resource Usage:
```bash
# Verify container statuses
docker compose -f monitoring/compose.yml ps

# Inspect live RAM and CPU consumption
docker stats victoria-metrics cadvisor node-exporter grafana --no-stream
```

### Verifying Service Endpoints:
```bash
# VictoriaMetrics health
curl -s http://127.0.0.1:8428/health

# VictoriaMetrics active targets
curl -s http://127.0.0.1:8428/api/v1/targets | jq .

# Node Exporter metrics
curl -s http://127.0.0.1:9100/metrics | grep node_cpu_seconds_total | head -n 5

# cAdvisor health
curl -s http://127.0.0.1:8080/healthz

# Grafana API health
curl -s http://127.0.0.1:3000/api/health
```

---

## 6. Reverse Proxy & Declarative Dashboards

### 6.1 Nginx Proxy Manager (NPM) Configuration
Grafana connects to the external `nginx-proxy-manager` Docker bridge network, allowing secure routing without exposing container ports to the public host interface:

- **Domain Names**: `monitoring.cloud.jacobmiller22.com`
- **Scheme / Forward Host / Port**: `http` / `grafana` / `3000`
- **SSL / TLS**: Let's Encrypt Wildcard certificate (`*.cloud.jacobmiller22.com`)
- **SSL Flags**:
  - `Force SSL`: Enabled
  - `HTTP/2 Support`: Enabled
  - `HSTS Enabled`: Enabled
- **Advanced / WebSockets**: `Websockets Support: Enabled` (required for live Grafana alerts and streaming panels)

### 6.2 Pre-Provisioned Dashboards
Grafana automatically loads declarative dashboards from `monitoring/grafana/dashboards/`:

1. **Host Overview & Capacity (bjorn)** (`host-metrics.json`):
   - **UID**: `host-overview`
   - **Live Storage Gauges**: Root filesystem total, used, free storage (GB), and % utilization on `/host`.
   - **Live Memory Gauges**: Total RAM, Used RAM, Available RAM, and Swap (Used, Total, Free).
   - **CPU & System Load**: Host CPU utilization % and 1m/5m/15m system load averages.
   - **Network Throughput**: Aggregate WAN/LAN upload/download bandwidth across non-virtual interfaces.

2. **Container Telemetry & Resource Attribution** (`container-metrics.json`):
   - **UID**: `container-telemetry`
   - **Container Filter**: Templated query variable dynamically populating container names with an `All` option.
   - **Top 10 CPU Consumers**: Ranked CPU utilization % per container over 5-minute rates.
   - **Top 10 Memory Consumers**: Ranked RAM working set bytes per container.
   - **Top Network Consumers**: Ingress (RX) and Egress (TX) bandwidth per container.
   - **Top Disk I/O Consumers**: Read and write throughput per container.

---

## 7. Proactive Discord Threshold Alerting

The monitoring stack implements declarative, GitOps-provisioned threshold alerting via Grafana unified alerting (`monitoring/grafana/provisioning/alerting/alerting.yaml`). Alerts evaluate against metrics stored in VictoriaMetrics and dispatch directly to a Discord webhook channel.

### 7.1 Alert Rule Inventory

| Alert UID | Rule Name | Threshold Condition | For Duration | Severity | Target Entity | Actionable Response |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `alert-disk-warning` | Host Disk Exhaustion (Warning) | Host rootfs utilization > 80% | 15m | `warning` | Host (`bjorn`) | Prune stale Docker images/build cache (`docker image prune -a`), inspect large logs in `/var/log`. |
| `alert-disk-critical` | Host Disk Exhaustion (Critical) | Host rootfs utilization > 90% | 5m | `critical` | Host (`bjorn`) | Urgent triage required to prevent filesystem switching to read-only mode. Clean disk partitions immediately. |
| `alert-memory-starvation` | Host Memory Starvation | Available host RAM < 10% | 10m | `critical` | Host (`bjorn`) | Risk of Linux OOM killer terminating core services. Inspect memory hogs (`docker stats`) and restart leaky sidecars. |
| `alert-container-down` | Container Down or Crash Looping | Core container metrics missing > 60s | 2m | `critical` | Core containers (`actual_server`, `vaultwarden`, `nginx-proxy-manager`, `homeassistant`) | Core workload crashed or restarting in a loop. Inspect container logs (`docker logs --tail 100 <container>`). |
| `alert-cpu-saturation` | Sustained Host CPU Saturation | Continuous non-idle CPU > 95% | 20m | `warning` | Host (`bjorn`) | Host under persistent compute stress. Check for stuck processes or unbounded ffmpeg/ML transcoding jobs. |

### 7.2 Discord Contact Point & Notification Routing

- **Contact Point**: `Discord-Alerts` (receiver `discord-notifier`, type `discord`).
- **Webhook Ingestion**: Injected dynamically via environment variable `DISCORD_WEBHOOK_URL` in `compose.yml`.
  > [!IMPORTANT]
  > Never commit a raw Discord webhook URL into version control. In production on `bjorn`, inject `DISCORD_WEBHOOK_URL` via Coolify environment variables or host-level `.env`.
- **Notification Policy Timing**:
  - `group_by: ['alertname', 'cluster', 'service']`: Correlates related alerts to prevent notification spam.
  - `group_wait: 30s`: Waits 30s to batch concurrent state transitions into a single Discord message.
  - `group_interval: 5m`: Minimum interval between sending notifications for an existing active group.
  - `repeat_interval: 4h`: Re-alerts every 4 hours if a critical issue remains unacknowledged and active.

### 7.3 Alert Testing & Drill Simulation Runbook

To safely verify alert firing, evaluation pipelines, and Discord delivery without jeopardizing production services:

#### 1. Dry-Run Discord Webhook Verification
Test the Discord webhook URL directly:
```bash
curl -H "Content-Type: application/json" \
     -X POST \
     -d '{"content": "🧪 **Drill Test**: Grafana Alertmanager Discord connectivity test from bjorn."}' \
     "${DISCORD_WEBHOOK_URL}"
```

#### 2. Verify Alert Rules in Grafana
Query the Grafana Alerting API on `bjorn`:
```bash
# Verify provisioned alert rule groups are loaded
curl -s -u admin:admin http://127.0.0.1:3000/api/v1/provisioning/alert-rules | jq .

# Verify provisioned contact points
curl -s -u admin:admin http://127.0.0.1:3000/api/v1/provisioning/contact-points | jq .
```

#### 3. Simulating Host Memory Starvation (Drill)
Using `stress-ng` (or a temporary memory allocation container) restricted to a short duration:
```bash
# Allocate temporary memory buffer for 60 seconds to observe metric change in VictoriaMetrics
docker run --rm -m 512m alpine sh -c "head -c 400m </dev/urandom >/dev/null"
```
Verify the expression `(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100` drops in the Grafana Explore tab or via VictoriaMetrics PromQL query:
```bash
curl -G http://127.0.0.1:8428/api/v1/query \
     --data-urlencode 'query=(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100' | jq .
```

#### 4. Simulating Container Down Alert (Drill)
Simulate an offline container using a non-critical test container:
```bash
# Launch a dummy container matching the metric pattern or inspect query:
curl -G http://127.0.0.1:8428/api/v1/query \
     --data-urlencode 'query=time() - container_last_seen{name=~"actual_server|vaultwarden|nginx-proxy-manager|homeassistant"} > 60' | jq .
```
Observe that when all containers are active, `container_last_seen` stays within 15 seconds of `time()`, producing zero active alerts.

