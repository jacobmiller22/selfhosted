# Grafana Dashboards

This directory contains declarative JSON dashboard definitions provisioned automatically by Grafana upon container startup.

## Provisioned Dashboards Overview

Dashboards placed in this directory are monitored and hot-reloaded by the Grafana file provider configured in `monitoring/grafana/provisioning/dashboards/dashboards.yml`.

### Standard Homelab Dashboards:
1. **Host Overview & Capacity (bjorn)** (`host-metrics.json`):
   - UID: `host-overview`
   - Focus: Live root `/host` filesystem utilization (Total, Used, Free in GB, % Used), RAM & Swap breakdown (MemTotal, MemAvailable, SwapUsed), CPU % with load averages (1m/5m/15m), host network throughput.
2. **Container Telemetry & Attribution** (`container-metrics.json`):
   - UID: `container-telemetry`
   - Focus: Top 10 CPU-consuming containers, Top 10 Memory-consuming containers (working set bytes), container network throughput (RX / TX), and disk I/O throughput (Read / Write). Includes container multi-select variable filter.
3. **VictoriaMetrics TSDB Vitals**:
   - Focus: Ingestion rate (samples/sec), active time-series count, storage size on disk, query latency percentiles.

## Adding Custom Dashboards
1. Build or customize a dashboard in the Grafana UI (`https://monitoring.cloud.jacobmiller22.com`).
2. Export the dashboard JSON (**Dashboard Settings** -> **JSON Model** -> **Save to file**).
3. Save the JSON file in this directory (`monitoring/grafana/dashboards/<dashboard-name>.json`).
4. Commit the JSON file to Git to ensure configuration parity across redeployments.
