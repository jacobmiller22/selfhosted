# Infrastructure Topology & Host Registry

This document defines the central inventory, network topology, and access protocols for all infrastructure managed in this repository.

---

## 1. Executive Summary & Host Registry

All production containers and workloads managed in this repository reside on remote bare-metal/server infrastructure. **No runtime service runs on local development machines (`localhost`).**

### Host Inventory

| Host ID | Hostname / DNS | Primary Role | OS / Kernel | Container Engine | Ingress / Routing | Remote Storage |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`bjorn`** *(Primary)* | `bjorn` (Tailscale MagicDNS)<br>`192.168.1.x` (LAN) | Primary Application & Storage Host | Linux (x86_64) | Docker Engine + Coolify Orchestrator | Nginx Proxy Manager (`*.cloud.jacobmiller22.com`) | Backblaze B2 (`secure-backup` bucket) |

---

## 2. Remote Access Protocols

### 2.1 Direct SSH Access
- **SSH Target**: `ssh bjorn` (configured via `~/.ssh/config` using ED25519 key authentication).
- **Execution Standard**: All remote administrative and Docker commands are dispatched over SSH:
  ```bash
  ssh bjorn "<command>"
  ```
- **Non-Interactive Verification**:
  ```bash
  ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"
  ```

### 2.2 Tailscale MagicDNS
- All hosts participate in the Tailscale private mesh network.
- Internal administrative web interfaces and service ports are directly reachable by authenticated devices via MagicDNS:
  - `http://bjorn:<port>` (e.g., NPM admin UI: `http://bjorn:81`, Vaultwarden host port: `http://bjorn:7277`).

### 2.3 Reverse Proxy Ingress (Nginx Proxy Manager)
- Central reverse proxy on `bjorn` binds to host ports `80` and `443`.
- SSL termination handled via automated Let's Encrypt certificates.
- Public/internal domain namespace: `https://*.cloud.jacobmiller22.com`.

### 2.4 Remote Storage Target (Backblaze B2)
- **Bucket**: `secure-backup` (or `jacobmiller22-secure-backup`).
- **Endpoint**: S3-compatible B2 endpoint (`s3.<region>.backblazeb2.com`).
- **Encryption**: AES-256-CBC PBKDF2 (100,000 iterations) via POSIX OpenSSL before transport.
- **Retention**: 30-day lifecycle rule with automated non-destructive timestamp rotation.

---

## 3. Hosted Service Map (Target Host: `bjorn`)

| Service Directory | Container Name(s) | Internal Port(s) | Host Port / Network | Public Domain / Ingress | Storage / Persistent Volumes | Critical Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`actual/`** | `actual_server`<br>`actual-backup`<br>`actual-auto-categorizer` | `5006`<br>N/A<br>`3080` | `3080:3080`<br>`nginx-proxy-manager` network | `https://budget.cloud.jacobmiller22.com` | Volume `actual-data` (`/data`) | TypeScript ML sidecar auto-syncs transactions; backup runner performs non-blocking SQLite snapshots. |
| **`homeassistant/`** | `homeassistant` | `8123` | `network_mode: host`<br>Port `8123` on host | `https://ha.cloud.jacobmiller22.com` | Bind mount `./config` (`/config`), `/run/dbus`, `/etc/localtime` | Requires WebSocket support enabled in NPM (`/api/websocket`); trusted proxies configured in `configuration.yaml`. |
| **`vaultwarden/`** | `vaultwarden`<br>`vw-backup` | `80`<br>N/A | `7277:80`<br>`nginx-proxy-manager` network | `https://vw.cloud.jacobmiller22.com` | Volume `vw-data` (`/data`) | Bitwarden password vault. Requires SQLite `.backup` locking protection; `rsa_key.pem` permissions `600`; read-only backup mount. |
| **`nginx-proxy-manager/`** | `nginx-proxy-manager` | `80`, `443`, `81`, `8096` | `80:80`, `443:443`, `81:81`, `8096:8096`<br>`nginx-proxy-manager` + `coolify` | `http://bjorn:81` (Admin)<br>Reverse proxy for all subdomains | Bind `./data` (`/data`), `./letsencrypt` (`/etc/letsencrypt`) | Central ingress router for all SSL domains and WebSockets; stores TLS certs and route DB in SQLite. |
| **`reiner-cam/`** | `motion` | Motion stream | Device `/dev/video0`<br>`nginx-proxy-manager` | Camera stream via proxy | Bind `./reiner-cam/data/motion/motion.conf` | Privileged container accessing local video capture hardware. |
| **`obsidian/`** | `livesync-db` | `5984` | `5984:5984`<br>`nginx-proxy-manager` network | `https://obsidian.cloud.jacobmiller22.com` | Bind `./db/data` (`/opt/couchdb/data`) | CouchDB 3.3.3 database powering Obsidian LiveSync across desktop and mobile devices. |
| **`tools/backup-runner/`** | Ephemeral or cron runners | N/A | Host network or service network | N/A | S3/B2 remote endpoint | POSIX OpenSSL AES-256-CBC PBKDF2 encryption engine; Discord error traps; Dead Man's Snitch monitoring. |

### 3.1 Ephemeral Staging Environments (`profiles: ["staging"]`)

For comprehensive staging specifications, see [docs/STAGING_ARCHITECTURE.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-35-staging-profiles/docs/STAGING_ARCHITECTURE.md).

| Staging Service | Container Name | Staging Host Port | Resource Cap | Dedicated Staging Volume | Network | Profile |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Actual Budget Staging** | `actual-server-staging` | `5006` | 256MB RAM / 0.50 CPU | `actual-stage-data` | `staging-net` | `staging` |
| **Vaultwarden Staging** | `vaultwarden-staging` | `7278` | 256MB RAM / 0.50 CPU | `vw-stage-data` | `staging-net` | `staging` |

---

## 4. Architectural Relationship & Network Topology

```
                                  INTERNET / TAILSCALE MESH
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       │                                           │
         HTTPS: *.cloud.jacobmiller22.com              Tailscale / LAN Direct
                       │                                           │
                       ▼                                           ▼
       ┌────────────────────────────────────────────────────────────────────────┐
       │ Host: bjorn (Linux x86_64, Docker Engine, Coolify Orchestration)        │
       │                                                                        │
       │  ┌──────────────────────────────────────────────────────────────────┐  │
       │  │ Reverse Proxy Gateway: nginx-proxy-manager                       │  │
       │  │  - Public Ports: 80 (HTTP), 443 (HTTPS)                          │  │
       │  │  - Admin Web UI: 81 (http://bjorn:81)                            │  │
       │  │  - SSL Certificates: /etc/letsencrypt                            │  │
       │  └──────┬──────────────────────┬───────────────────────┬────────────┘  │
       │         │                      │                       │               │
       │         ▼                      ▼                       ▼               │
       │  ┌──────────────┐      ┌───────────────┐       ┌───────────────┐       │
       │  │ Actual Budget│      │ Vaultwarden   │       │ Obsidian Sync │       │
       │  │ :5006        │      │ :7277 (-> :80)│       │ :5984         │       │
       │  │ Sidecar :3080│      │ Volume vw-data│       │ CouchDB 3.3.3 │       │
       │  └──────────────┘      └───────────────┘       └───────────────┘       │
       │         │                      │                                       │
       │         └──────────┬───────────┘                                       │
       │                    ▼ (Host Networking)                                 │
       │         ┌──────────────────────┐               ┌───────────────┐       │
       │         │ Home Assistant       │               │ Reiner-Cam    │       │
       │         │ :8123 (Host Network) │               │ /dev/video0   │       │
       │         └──────────────────────┘               └───────────────┘       │
       │                                                                        │
       │  ┌──────────────────────────────────────────────────────────────────┐  │
       │  │ Universal Backup Runners (Alpine)                                │  │
       │  │  - Non-blocking SQLite snapshot (.backup)                        │  │
       │  │  - OpenSSL AES-256-CBC PBKDF2 encryption                         │  │
       │  │  - Discord error alerts on failure, Dead Man's Snitch on success  │  │
       │  └─────────────────────────────────┬────────────────────────────────┘  │
       └────────────────────────────────────┼───────────────────────────────────┘
                                            │ TLS Encrypted Transport
                                            ▼
                           ┌─────────────────────────────────┐
                           │ Backblaze B2: secure-backup     │
                           │  - 30-day versioned retention   │
                           └─────────────────────────────────┘
```

---

## 5. Extensible Host Schema (Future Expansion Blueprint)

When adding future compute or storage nodes (such as edge VPS instances, Raspberry Pi hardware bridges, or NAS storage servers), record their configuration following this standardized schema:

```yaml
host_id: <unique-identifier>           # e.g., rpi-livingroom-01, vps-us-east, truenas-core
hostname: <network-hostname>           # e.g., rpi-livingroom.tailscale.net
role: <primary-role>                   # e.g., Zigbee Coordinator, Public Edge Relay, Mass Storage
os: <operating-system>                 # e.g., Debian 12 (bookworm) aarch64
access:
  ssh_alias: <ssh-config-alias>        # e.g., ssh rpi01
  tailscale_ip: <100.x.y.z>
  lan_ip: <192.168.1.x>
runtime:
  engine: <docker | podman | bare-metal>
  orchestration: <compose | coolify | systemd>
storage:
  volumes_root: </path/to/volumes>
  backup_target: <b2-bucket-name | local-zpool>
services:
  - name: <service-name>
    directory: <relative-repo-path>
    port: <container-or-host-port>
    ingress: <public-url-or-local-ip>
    backup_strategy: <sqlite3-snapshot | file-archive | db-dump>
```

### Reference Future Host Profiles

#### Profile A: Edge VPS Gateway (`vps-edge-01`)
- **Role**: Cloud WireGuard relay and public DMZ ingress router for split-horizon DNS.
- **Access**: `ssh vps-edge-01`.
- **Services**: Cloudflare Tunnel connectors, WireGuard bounce relay.

#### Profile B: Hardware Peripheral Coordinator (`rpi-coordinator-01`)
- **Role**: Raspberry Pi 4/5 co-located with physical sensors and antennas.
- **Access**: `ssh rpi01`.
- **Services**: Zigbee2MQTT with USB CC2652P coordinator, Bluetooth proxy for Home Assistant.

#### Profile C: High-Capacity Storage Node (`nas-storage-01`)
- **Role**: ZFS storage pool for raw media archives, NVR camera retention, and secondary snapshot replicas.
- **Access**: `ssh nas01`.
- **Services**: Samba/NFS shares, automated cold-storage staging.
