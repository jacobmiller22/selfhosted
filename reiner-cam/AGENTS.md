# Reiner-Cam Directives (`reiner-cam/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Compose Stack**: `reiner-cam/compose.yml`  
> **Hardware Device**: `/dev/video0`

---

## 1. Architecture Overview

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine).
- **Service**: Motion video stream capture container (`motion`).
- **Role**: USB webcam feed processing and motion detection.
- **Privileges**: Container requires `privileged: true` and hardware passthrough for `/dev/video0:/dev/video0`.
- **Networks**: `nginx-proxy-manager` external network.
- **Storage**: Bind mount `./reiner-cam/data/motion/motion.conf` to `/etc/motion/motion.conf`.

---

## 2. Remote Host Verification Protocol for `reiner-cam/`

All management actions run remotely on `bjorn`:

```bash
# Verify host reachability
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"

# Verify video hardware device exists on host bjorn
ssh bjorn "ls -l /dev/video*"

# Check container status
ssh bjorn "docker ps --filter name=motion"

# Inspect motion capture logs
ssh bjorn "docker logs --tail 100 motion"

# Restart camera container
ssh bjorn "docker restart motion"
```

---

## 3. Operational Safeguards

- **Hardware Dependencies**: This container cannot function in a standard cloud VM or headless server without a connected USB camera node at `/dev/video0`.
- **Hardware Disconnects**: If the camera disconnects or reconnects, the host Linux kernel may reassign `/dev/video0` to `/dev/video1`. Verify device path via `v4l2-ctl --list-devices` on `bjorn`.
