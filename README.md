# Self-Hosted Infrastructure & GitOps Monorepo

Welcome to the central infrastructure monorepo managing production homelab services, automation workflows, GitOps deployment pipelines, and disaster recovery runners.

---

## 1. Remote-First Operational Directives

> [!CRITICAL]
> **This repository manages REMOTE production server infrastructure.**
> **All containers, volumes, reverse proxy routes, and system services execute on remote bare-metal Linux servers (primary host: `bjorn`).**
> **NEVER assume `localhost`, `127.0.0.1`, or local Docker daemon execution for runtime operations.**

- **Primary Host**: `bjorn` (Linux x86_64, Docker Engine + Coolify Orchestrator).
- **Network Ingress**: Tailscale MagicDNS (`http://bjorn:<port>`) and public reverse proxy endpoints (`https://*.cloud.jacobmiller22.com`).
- **Remote Host Verification Protocol (RHVP)**: Test reachability before dispatching commands:
  ```bash
  ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"
  ssh bjorn "docker ps"
  ```

---

## 2. Architecture & Operational Runbooks

Authoritative architectural specifications, network diagrams, disaster recovery procedures, and deployment runbooks are documented in [`docs/`](docs/):

| Document | Focus Area | Description |
| :--- | :--- | :--- |
| [`docs/INFRASTRUCTURE_TOPOLOGY.md`](docs/INFRASTRUCTURE_TOPOLOGY.md) | Infrastructure & Topology | Central inventory of hosts, ports, networks, and remote access protocols |
| [`docs/CI_CD_COOLIFY_PIPELINE.md`](docs/CI_CD_COOLIFY_PIPELINE.md) | CI/CD & Deployments | Automated PR & webhook deployment pipeline, NPM vs. Traefik ingress, service onboarding, and secret rotation |
| [`docs/BACKUP_ARCHITECTURE.md`](docs/BACKUP_ARCHITECTURE.md) | Backup Architecture | Standardized OpenSSL AES-256-CBC PBKDF2 backup engine, B2 cloud retention, and alerting |
| [`docs/RESTORE.md`](docs/RESTORE.md) | Disaster Recovery & Restoration | Step-by-step restoration runbooks for Actual, Vaultwarden, Home Assistant, and NPM |
| [`docs/MONITORING_ARCHITECTURE.md`](docs/MONITORING_ARCHITECTURE.md) | Telemetry & Observability | Low-footprint monitoring stack (VictoriaMetrics, cAdvisor, Node Exporter, Grafana) |
| [`docs/PM_ARCHITECT.md`](docs/PM_ARCHITECT.md) | Autonomous TPM Engine | Architectural Council, Benevolent Dictator homelab axioms, and reality fact-checking engine |

---

## 3. Hosted Service Map (Target Host: `bjorn`)

| Service Directory | Core Containers | Internal Port | Ingress Domain / Route | Primary Role |
| :--- | :--- | :--- | :--- | :--- |
| [`actual/`](actual/) | `actual_server`<br>`actual-auto-categorizer`<br>`actual-backup` | `5006`<br>`3080` | `https://budget.cloud.jacobmiller22.com` | Personal finance management, local bank statement importer, and ML auto-categorizer sidecar. |
| [`homeassistant/`](homeassistant/) | `homeassistant` | `8123` | `https://ha.cloud.jacobmiller22.com` | Home automation hub running in `network_mode: host` with WebSocket ingress. |
| [`vaultwarden/`](vaultwarden/) | `vaultwarden`<br>`vw-backup` | `7277` (host)<br>`80` (container) | `https://vw.cloud.jacobmiller22.com` | Bitwarden-compatible password vault with SQLite `.backup` locking protection. |
| [`nginx-proxy-manager/`](nginx-proxy-manager/) | `nginx-proxy-manager` | `80`, `443`, `81` | `http://bjorn:81` (Admin)<br>`*.cloud.jacobmiller22.com` | Central reverse proxy gateway, SSL/TLS Let's Encrypt termination, and preview wildcard router. |
| [`obsidian/`](obsidian/) | `livesync-db` | `5984` | `https://obsidian.cloud.jacobmiller22.com` | CouchDB 3.3.3 backend powering Obsidian LiveSync across devices. |
| [`reiner-cam/`](reiner-cam/) | `motion` | Motion stream | Camera stream via proxy | Security camera streaming daemon accessing USB video capture hardware (`/dev/video0`). |
| [`monitoring/`](monitoring/) | `victoriametrics`<br>`cadvisor`<br>`node-exporter`<br>`grafana` | `8428`<br>`8080`<br>`9100`<br>`3000` | `https://grafana.cloud.jacobmiller22.com` | Unified lightweight telemetry and observability stack (< 200MB aggregate RAM footprint). |
| [`tools/backup-runner/`](tools/backup-runner/) | Alpine backup runner | N/A | S3 / Backblaze B2 Target | Universal OpenSSL AES-256-CBC PBKDF2 backup engine with Discord and Dead Man's Snitch alerting. |

---

## 4. Continuous Integration & Deployment Pipeline

Continuous deployment is driven through a decoupled dual-router architecture:
- **Pre-Deployment Gates (`.github/workflows/ci.yml`)**: Automated syntax validation for Compose files, ShellCheck linting, secret scanning, Python unit tests, and backup roundtrip tests.
- **Webhook Ingress**: GitHub PR events dispatch signed payloads to Nginx Proxy Manager (Port 443), forwarding internally to Coolify (Port 8080) across the `coolify` Docker network.
- **Coolify Orchestrator**: Authenticates HMAC signatures (`X-Hub-Signature-256`), checks modified files against configured `watch_paths`, and orchestrates container builds on `bjorn`.
- **Dynamic PR Previews**: Ephemeral containers are tagged with Traefik labels, instantly discoverable on port 50080 and routed through NPM wildcard certificates (`*.preview.cloud.jacobmiller22.com`).

For complete operational details, onboarding checklists, troubleshooting commands, and secret rotation runbooks, see [`docs/CI_CD_COOLIFY_PIPELINE.md`](docs/CI_CD_COOLIFY_PIPELINE.md).

---

## 5. Development & Verification Commands

All modifications must pass the local verification suite before opening a Pull Request:

```bash
# 1. Run Python Unit Tests
python3 -m unittest discover -s tests -p "test_*.py"

# 2. Run Backup & Disaster Recovery Architecture Verification
./tools/backup-runner/test-backup-restore.sh

# 3. Validate Docker Compose Syntax
docker compose -f actual/compose.yml config --quiet
docker compose -f nginx-proxy-manager/compose.yml config --quiet
docker compose -f vaultwarden/compose.yml config --quiet
docker compose -f homeassistant/compose.yml config --quiet
docker compose -f obsidian/compose.yml config --quiet
docker compose -f reiner-cam/compose.yml config --quiet
```
