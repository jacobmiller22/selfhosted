---
name: coolify-docker-ops
description: Operations and troubleshooting workflows for Coolify-managed Docker containers and sidecar daemons on server bjorn.
---

# Coolify Docker Operations & Sidecar Deployment Skill

This skill provides step-by-step procedures for managing, debugging, and hot-patching Docker container services deployed via Coolify on remote server `bjorn`.

## Container Architecture Overview

- **Host Server**: `bjorn`
- **Docker Compose Stack**: `actual/compose.yml`
  - `actual_server`: Main Actual Budget container (port `5006`).
  - `actual-backup`: Automated SQLite backup runner.
  - `actual-auto-categorizer`: TypeScript ML sidecar daemon (port `3080`).

---

## Command Workflows

### 1. Inspecting Container Status & Logs
Run SSH commands non-interactively to inspect Docker state:

```bash
# Check container status
ssh bjorn "docker ps --filter name=actual"

# View recent container logs
ssh bjorn "docker logs --tail 100 actual-auto-categorizer-g8woog40sgkcogwkcksgwwoc"
```

### 2. Exposing Container Ports in `compose.yml`
To allow local/host HTTP access to sidecar REST endpoints (port 3080), ensure `ports` mapping is explicitly declared in `actual/compose.yml`:

```yaml
  actual-auto-categorizer:
    build:
      context: ./tools/auto-categorizer
      dockerfile: Dockerfile
    container_name: actual-auto-categorizer
    ports:
      - "3080:3080"
    restart: unless-stopped
```

### 3. Hot-Patching Built Dist & Models (Rapid Verification Workflow)
When validating updates before a full Coolify git build cycle completes:

```bash
# 1. Compile TypeScript locally
npm run build --prefix actual/tools/auto-categorizer

# 2. Upload compiled dist files to bjorn and copy into container
scp -r actual/tools/auto-categorizer/dist/* bjorn:/tmp/auto-categorizer-dist/
ssh bjorn "docker cp /tmp/auto-categorizer-dist/. actual-auto-categorizer-g8woog40sgkcogwkcksgwwoc:/app/dist/"

# 3. Upload updated ONNX models
scp -r actual/auto-categorizer-models/* bjorn:/tmp/auto-categorizer-models/
ssh bjorn "docker cp /tmp/auto-categorizer-models/. actual-auto-categorizer-g8woog40sgkcogwkcksgwwoc:/app/src/models/"

# 4. Restart container
ssh bjorn "docker restart actual-auto-categorizer-g8woog40sgkcogwkcksgwwoc"
```

### 4. Executing Manual REST API Commands
Because alpine containers may lack `curl`, use Node.js `fetch` via `docker exec`:

```bash
# Health Check Endpoint
ssh bjorn "docker exec actual-auto-categorizer-g8woog40sgkcogwkcksgwwoc node -e '
fetch(\"http://localhost:3080/health\").then(r => r.json()).then(console.log).catch(console.error);
'"

# Trigger Manual Sync Cycle
ssh bjorn "docker exec actual-auto-categorizer-g8woog40sgkcogwkcksgwwoc node -e '
fetch(\"http://localhost:3080/api/sync\", { method: \"POST\" })
  .then(r => r.json())
  .then(data => console.log(\"Sync Result:\", data))
  .catch(console.error);
'"
```
