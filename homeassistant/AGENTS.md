# Home Assistant Directives (`homeassistant/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `homeassistant/compose.yml`  
> **Ingress Domain**: `https://ha.cloud.jacobmiller22.com`

---

## 1. Architecture & Networking

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine).
- **Networking Mode**: **`network_mode: host`**
  - Home Assistant binds directly to host interfaces on port `8123` to enable mDNS, UPnP, SSDP, and HomeKit local device discovery.
  - Privileged container access enabled for D-Bus (`/run/dbus`) and local device hardware.
- **Persistent Storage**:
  - Bind mount `./config` mapped to `/config` in the container.
  - Core database: `/config/home-assistant_v2.db`.
  - Credentials and integration tokens: `/config/.storage/`.

---

## 2. Remote Host Verification Protocol for `homeassistant/`

All management actions run remotely on `bjorn`:

```bash
# Verify host reachability
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"

# Check Home Assistant container
ssh bjorn "docker ps --filter name=homeassistant"

# Inspect live logs
ssh bjorn "docker logs --tail 100 homeassistant"

# Restart Home Assistant container
ssh bjorn "docker restart homeassistant"

# Check port 8123 response on bjorn
ssh bjorn "curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:8123"
```

---

## 3. Reverse Proxy & Ingress Standards (NPM)

Home Assistant is routed through **Nginx Proxy Manager** at `https://ha.cloud.jacobmiller22.com`:

1. **WebSockets Support Mandatory**:
   - The **Websockets Support** toggle MUST remain **ON** in NPM for the `ha.cloud.jacobmiller22.com` proxy host.
   - Home Assistant uses `/api/websocket` for streaming live entity state changes. Disabling WebSockets causes continuous disconnect loops in the frontend.
2. **Reverse Proxy Security (`trusted_proxies`)**:
   - `homeassistant/config/configuration.yaml` MUST configure the `http` integration with `use_x_forwarded_for: true` and list the Docker network bridges (e.g. `172.16.0.0/12`, `172.17.0.0/16`, `127.0.0.1`):
     ```yaml
     http:
       use_x_forwarded_for: true
       trusted_proxies:
         - 172.16.0.0/12
         - 172.17.0.0/16
         - 172.18.0.0/16
         - 172.19.0.0/16
         - 10.0.0.0/8
         - 127.0.0.1
     ```
   - Failing to declare `trusted_proxies` results in `400 Bad Request` or blocked ingress from NPM.

---

## 4. Configuration & Secret Hygiene

- **`secrets.yaml` Protection**:
  - NEVER commit `/config/secrets.yaml` or any file containing API tokens, passwords, or GPS home coordinates to Git.
  - Keep `secrets.yaml` strictly gitignored.
- **UI-First Integration Pattern**:
  - Smart devices (Ecobee, Hue, Kasa, Sonos, Shelly, Nest, Tuya) should be onboarded via the Home Assistant UI (**Settings** -> **Devices & Services**), NOT hand-coded in YAML.
  - Reserve `configuration.yaml` for structural platform declarations, template sensors, and network security settings.
- **Database Snapshots**:
  - To snapshot `home-assistant_v2.db` without locking corruption:
    ```bash
    ssh bjorn "sqlite3 /config/home-assistant_v2.db '.backup /tmp/ha-backup.sqlite'"
    ```
