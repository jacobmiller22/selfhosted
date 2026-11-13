# Antigravity & Gemini Agent Directives (`GEMINI.md`)

This file guides Google Antigravity and Gemini-based AI coding agents operating within the `selfhosted` repository.

---

## 1. Remote-First Operational Rule

> [!CRITICAL]
> **ALL infrastructure managed by this repository runs on remote hosts (primary host: `bjorn`).**
> **NEVER assume `localhost`, `127.0.0.1`, or local Docker daemon execution for service runtime commands.**

- The local environment is a macOS workstation used strictly for code editing, version control, and dispatching SSH commands.
- Production and staging workloads execute on remote Linux servers running Docker Engine and Coolify.
- Access endpoints use Tailscale MagicDNS (`http://bjorn:<port>`) or public SSL reverse proxy routes (`https://*.cloud.jacobmiller22.com`).

---

## 2. Remote Host Verification Protocol (RHVP)

When prompted to inspect, run, restart, debug, or test any service or container:

1. **Host Discovery**:
   - Check the service's local `AGENTS.md` or consult [docs/INFRASTRUCTURE_TOPOLOGY.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-40-remote-host-verification/docs/INFRASTRUCTURE_TOPOLOGY.md).
   - Identify the target host (default: `bjorn`).
2. **Connectivity Check**:
   - Test SSH connection before running long commands:
     ```bash
     ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"
     ```
3. **Execution Pattern**:
   - Wrap all runtime commands in SSH:
     ```bash
     ssh <target-host> "<command>"
     ```
   - Examples:
     ```bash
     ssh bjorn "docker ps --filter name=actual"
     ssh bjorn "docker logs --tail 50 homeassistant"
     ssh bjorn "docker restart nginx-proxy-manager"
     ```
4. **File Transfer & Live Testing**:
   - Use `scp` or `rsync` to transfer builds/models into `/tmp` on `bjorn`, then `ssh bjorn "docker cp ..."` into containers.

---

## 3. Outside-In Remote Deployment Verification Protocol (ODVP)

> [!CRITICAL]
> **Container presence on `bjorn` does NOT confirm service availability.**
> All deployments must be verified across 5 operational layers from container stability to client-side HTTPS egress:

- **L1: Container Stability & Healthcheck Latch (Remote)**:
  Assert container status is `running` and not caught in crash-restart loops:
  `ssh bjorn "docker inspect --format '{{.State.Status}}' <container>"`
- **L2: Internal Business Logic & Data Probe (Remote)**:
  Probe listening port directly on localhost to ensure daemon is active before routing:
  `ssh bjorn "curl -fsS http://localhost:<port>/"`
- **L3: Reverse Proxy & Bridge Network Verification (Remote)**:
  Validate proxy network bridge attachment:
  `ssh bjorn "docker inspect --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}' <container>"`
- **L4: Outside DNS & TLS Handshake Validation (Client Workstation)**:
  Verify DNS resolution and TLS certificate handshake from client workstation:
  `dig +short <domain> && curl -vI https://<domain>`
- **L5: Outside-In HTTPS Egress Probe (Client Workstation)**:
  Execute client-side HTTP egress probe; assert valid responses (200, 302, 401) and strictly disallow proxy failures (502, 504):
  `curl -fsS -o /dev/null -w "%{http_code}" https://<domain>`

### Automated Verification Harness
Run automated smoke verification via:
```bash
# Full 5-layer verification:
./tools/verify-deployment/verify_service.sh --host bjorn --service <container> --internal-port <port> --url <https-url>

# Client-only outside-in probe:
./tools/verify-deployment/verify_service.sh --skip-remote --url <https-url>

# Dry-run validation:
./tools/verify-deployment/verify_service.sh --service <container> --internal-port <port> --url <https-url> --dry-run
```

---

## 4. Git Worktree Protocol with Worktrunk (`wt`)

> [!IMPORTANT]
> **NEVER make code changes directly on the primary working tree or default branch (`main` or `master`).**
> Always spawn and switch to an isolated Git worktree using Worktrunk (`wt`).

- **Spawn/Switch**: `wt switch --create <branch-name>`
- **Isolation**: Ensure all `run_command` calls use `Cwd: /Users/jacobmiller22/projects/selfhosted.<branch-name>`.
- **Targeting**: Target all file viewing and editing operations within the worktree path.
- **Reporting**: Report the worktree branch name and directory to the user, and remind them of `wt merge` upon task completion.

---

## 5. Zero Untracked Work Protocol (`pm`)

> [!IMPORTANT]
> **NEVER perform untracked "ghost work" that is lost to history.**
> All work must be associated with a tracked task, GitHub issue, and Pull Request.

- Check open issues with `gh issue list`. If none exists, create one with `gh issue create`.
- Name branch after issue: `feature/<N>-<slug>` or `fix/<N>-<slug>`.
- Keep issue audit trail updated via `gh issue comment <N>`.
- Link PR with `Fixes #<N>`.
- Keep issue open with `status:completed` until PR is merged.

---

## 6. Security & Secret Protection

- **No Secrets in Git**: Never commit `.env`, `secrets.yaml`, private keys, passwords, or raw unencrypted backup databases.
- **Offline Passphrase Storage**: Master passphrases (`BACKUP_PASSPHRASE`) remain in physical offline safe storage; runtime services receive them via Coolify environment variables.
- **Safe Database Snapshots**: Always snapshot SQLite databases with `sqlite3 <db> ".backup <dest>"`. Never `cp` live databases while writers are active.

---

## 7. Service Directory Directory Pointers

Refer to the subsystem documentation and directives:
- [docs/INFRASTRUCTURE_TOPOLOGY.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-40-remote-host-verification/docs/INFRASTRUCTURE_TOPOLOGY.md) – Global topology and host registry
- [actual/AGENTS.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-40-remote-host-verification/actual/AGENTS.md) – Actual Budget & ML Auto-Categorizer
- [homeassistant/AGENTS.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-40-remote-host-verification/homeassistant/AGENTS.md) – Home Assistant & Ingress Configuration
- [vaultwarden/AGENTS.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-40-remote-host-verification/vaultwarden/AGENTS.md) – Bitwarden Vault & Permissions
- [nginx-proxy-manager/AGENTS.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-40-remote-host-verification/nginx-proxy-manager/AGENTS.md) – Central SSL Reverse Proxy
- [tools/backup-runner/AGENTS.md](file:///Users/jacobmiller22/projects/selfhosted.feature-task-40-remote-host-verification/tools/backup-runner/AGENTS.md) – OpenSSL Backup Runner & B2 Retention
