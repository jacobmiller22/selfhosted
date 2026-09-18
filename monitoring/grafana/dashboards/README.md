# Grafana Dashboards

This directory contains declarative JSON dashboard definitions provisioned automatically by Grafana upon container startup.

## Provisioned Dashboards Overview

Dashboards placed in this directory are monitored and hot-reloaded by the Grafana file provider configured in `monitoring/grafana/provisioning/dashboards/dashboards.yml`.

### Standard Homelab Dashboards (Implementation in #22):
1. **Host Overview (Node Exporter)**:
   - Community Base: Dashboard ID `1860` ("Node Exporter Full")
   - Focus: Live root `/` and `/var/lib/docker` filesystem utilization, RAM breakdown, CPU % with system/iowait, host network rx/tx rates, system load averages.
2. **Container Telemetry & Attribution (cAdvisor)**:
   - Community Base: Dashboard ID `14282` ("cAdvisor Exporter") or `893` ("Docker and System Monitoring")
   - Focus: Top CPU-consuming containers, container RSS vs page cache memory allocation, block I/O throughput (bytes/s, IOPS), container virtual network interface throughput.
3. **VictoriaMetrics TSDB Vitals**:
   - Focus: Ingestion rate (samples/sec), active time-series count, storage size on disk, query latency percentiles.

## Adding Custom Dashboards
1. Build or customize a dashboard in the Grafana UI (`https://monitoring.cloud.jacobmiller22.com`).
2. Export the dashboard JSON (**Dashboard Settings** -> **JSON Model** -> **Save to file**).
3. Save the JSON file in this directory (`monitoring/grafana/dashboards/<dashboard-name>.json`).
4. Commit the JSON file to Git to ensure configuration parity across redeployments.
