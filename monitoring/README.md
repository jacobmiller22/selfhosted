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
  Observability dashboard UI with automated file-based datasource and dashboard provisioning consuming **< 80MB RAM**.

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
    │   ├── datasources/
    │   │   └── datasources.yml               # Automated VictoriaMetrics Prometheus datasource
    │   └── dashboards/
    │       └── dashboards.yml                # File provider mapping for JSON dashboards
    └── dashboards/
        └── README.md                         # Dashboard templates, JSON definitions, and IDs
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

## 4. Resource Bounds (< 350MB RAM Steady-State)

Every container enforces strict hard resource limits in `compose.yml`:

| Container | Hard RAM Limit | RAM Reservation | Hard CPU Limit | Steady-State RAM |
| :--- | :--- | :--- | :--- | :--- |
| `victoria-metrics` | 128MB | 64MB | 0.25 CPU | ~35MB |
| `cadvisor` | 80MB | 40MB | 0.20 CPU | ~35MB |
| `node-exporter` | 30MB | 15MB | 0.10 CPU | ~15MB |
| `grafana` | 80MB | 40MB | 0.30 CPU | ~50MB |
| **Total Stack** | **318MB Hard Ceiling** | **159MB** | **0.85 CPU** | **~135MB** |

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
