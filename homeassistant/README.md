# Home Assistant Setup & Nginx Proxy Manager Guide

This directory contains the Docker Compose setup and configuration files for Home Assistant, optimized to run securely behind **Nginx Proxy Manager (NPM)**.

---

## 1. Complete Nginx Proxy Manager (NPM) Configuration Guide

Follow these step-by-step instructions to configure Nginx Proxy Manager for `https://ha.cloud.jacobmiller22.com`.

### Step 1: Open NPM Admin Interface
1. Open your web browser and navigate to the Nginx Proxy Manager admin panel (usually `http://<SERVER_IP>:81`).
2. Log in with your admin credentials.

---

### Step 2: Create Proxy Host

Navigate to **Hosts** -> **Proxy Hosts** and click **Add Proxy Host**.

#### A. Details Tab
Fill out the fields in the **Details** tab exactly as follows:

| Field | Value | Notes |
| :--- | :--- | :--- |
| **Domain Names** | `ha.cloud.jacobmiller22.com` | Ensure DNS A/AAAA record points to your server's public IP |
| **Scheme** | `http` | Home Assistant container runs standard HTTP internally |
| **Forward Hostname / IP** | `<SERVER_IP>` or `172.17.0.1` | The local LAN IP of your host server (e.g. `192.168.1.100`) or Docker gateway `172.17.0.1` |
| **Forward Port** | `8123` | Home Assistant default web port |
| **Cache Assets** | `OFF` | Keep disabled so dynamic home automation UI assets don't cache stale data |
| **Block Common Exploits** | `ON` | Adds standard security headers and blocks known exploit patterns |
| **Websockets Support** | **`ON`** | **CRITICAL!** Home Assistant streams real-time entity updates via WebSockets (`/api/websocket`). Disabling this will cause continuous UI disconnections and reconnecting loops. |

---

#### B. SSL Tab
Switch to the **SSL** tab:

1. **SSL Certificate**: Select **Request a new Let's Encrypt Certificate** (or choose an existing wild-card certificate if you have one).
2. **Email Address for Let's Encrypt**: Enter your email address for certificate renewal notifications.
3. Check the following toggles:
   - [x] **Force SSL** (Redirects all `http://` traffic to `https://`)
   - [x] **HTTP/2 Support** (Improves performance and multiplexing)
   - [x] **HSTS Enabled** (Optional, recommended for HTTPS enforcement)
   - [x] **I Agree to the Let's Encrypt Terms of Service**

---

#### C. Advanced Tab (Optional / Custom Headers)
Under normal circumstances, Home Assistant works out of the box with the **Websockets Support** toggle ON. However, if you experience WebSocket disconnects behind external proxies like Cloudflare, paste the following snippet into the **Custom Nginx Configuration** block:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

Click **Save** to apply the Proxy Host.

---

### Step 3: Troubleshooting NPM & Home Assistant Connection Issues

#### ❌ Issue 1: `400 Bad Request: HTTP request headers invalid` or `A request from a reverse proxy was received...`
- **Cause**: Home Assistant security features block proxies by default unless explicitly configured under `http.trusted_proxies`.
- **Fix**: Verify `homeassistant/config/configuration.yaml` contains the `http` configuration:
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
  Restart Home Assistant (`docker compose restart`) after updating `configuration.yaml`.

#### ❌ Issue 2: "Unable to connect to Home Assistant" or Endless Loading Spinner
- **Cause**: **Websockets Support** was not toggled ON in NPM, or Let's Encrypt SSL certificate issuance failed.
- **Fix**: 
  1. Re-open the Proxy Host in NPM and verify **Websockets Support** is checked `ON`.
  2. Verify ports `80` and `443` are reachable from the internet on your router if requesting Let's Encrypt certificates.

---

## 2. Smart Device Onboarding & Integration Guide

### Do I need to edit YAML files to add devices (e.g., Smart Thermostats, Lights, Plugs)?

**Short Answer: No!** Modern Home Assistant handles almost all smart home hardware through the **Graphical User Interface (UI)**.

#### 1. UI-Based Integrations (Standard)
Most popular device ecosystems (Ecobee, Nest, Honeywell, Philips Hue, TP-Link Kasa, Tuya, Sonos, Roku, Shelly, Ring, etc.) work via UI onboarding:
1. Open Home Assistant at `https://ha.cloud.jacobmiller22.com`.
2. Go to **Settings** -> **Devices & Services**.
3. Because `network_mode: host` is enabled in Docker, Home Assistant will automatically detect many devices on your home network and display a prompt saying **"Discovered"**.
4. Click **Configure** on the discovered device or click **Add Integration** in the bottom right, search for your device brand (e.g., *Ecobee* or *Nest*), and follow the authentication prompt.

#### 2. Thermostats & Climate Control
- **Ecobee / Nest / Honeywell**: Added via UI under **Devices & Services**. Once linked, your thermostat controls (temperature, mode, preset, humidity) will automatically populate on your dashboard.
- **Smart Thermostat Dashboards**: Home Assistant creates a standard `climate` entity (e.g., `climate.living_room_thermostat`) which can be added to any dashboard card with zero YAML configuration.

#### 3. When is YAML Configuration Needed?
You only need to edit files in `./config/` in specific advanced scenarios:
- **`secrets.yaml`**: To store sensitive values (API keys, passwords, coordinates). Reference them in `configuration.yaml` using `!secret key_name`. *(Note: `secrets.yaml` is ignored by `.gitignore` to keep credentials out of version control).*
- **Custom Template Sensors**: If you want to compute custom values (e.g., averaging two temperature sensors together).
- **MQTT / Custom integrations**: For DIY microcontrollers (ESPHome/Tasmota) or custom hardware integrations.

---

## 3. Configuration Directory Overview

```
homeassistant/
├── compose.yml           # Docker Compose container configuration
├── README.md             # Setup and onboarding documentation
└── config/
    ├── configuration.yaml # Core settings & HTTP proxy rules
    ├── automations.yaml   # UI & manual automations storage
    ├── scripts.yaml       # UI & manual scripts storage
    ├── scenes.yaml        # UI & manual scenes storage
    ├── secrets.yaml       # (Created on demand) Sensitive passwords/keys
    └── .storage/          # Internal state managed by Home Assistant UI (git-ignored)
```

---

## 4. Useful Docker Commands

- **Start Home Assistant**:
  ```bash
  docker compose up -d
  ```
- **View Container Logs**:
  ```bash
  docker compose logs -f
  ```
- **Restart Container**:
  ```bash
  docker compose restart
  ```
- **Stop Container**:
  ```bash
  docker compose down
  ```
