# Universal Backup Runner Directives (`tools/backup-runner/AGENTS.md`)

> **Target Remote Host**: `bjorn`  
> **Script Template**: `tools/backup-runner/backup-template.sh`  
> **Test Harness**: `tools/backup-runner/test-backup-restore.sh`  
> **Remote Cloud Target**: Backblaze B2 (`secure-backup` bucket)

---

## 1. Architecture Overview

- **Host Server**: `bjorn` (Linux x86_64, Docker Engine).
- **Container Base**: Lightweight Alpine Linux container (~45MB) equipped with:
  - `bash`, `coreutils`, `tar`, `gzip`
  - `openssl` (POSIX-standard cryptographic engine)
  - `sqlite` (`sqlite3` for non-blocking live database snapshots)
  - `curl` (for S3 API calls, Discord webhook alerts, and Healthcheck pings)
- **Encryption Standard**:
  - **Cipher**: AES-256-CBC
  - **Key Derivation**: PBKDF2 with HMAC-SHA256
  - **Iterations**: `100000`
  - **Salt**: 8-byte cryptographically random salt (`Salted__` header)
  - Zero proprietary dependencies; recoverable on any UNIX/Linux/macOS terminal with stock OpenSSL.

---

## 2. Remote Host Verification Protocol for `tools/backup-runner/`

All backup operations and validation tests run on remote host `bjorn`:

```bash
# Verify host reachability
ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn "echo ok"

# Check backup container execution status
ssh bjorn "docker ps -a --filter name=backup"

# Inspect latest backup container logs
ssh bjorn "docker logs --tail 100 actual-backup"
ssh bjorn "docker logs --tail 100 vw-backup"

# Trigger on-demand backup test run
ssh bjorn "docker exec actual-backup /scripts/backup.sh"
```

---

## 3. Reliability & Monitoring Protocols

### 3.1 Active Failure Trapping (Discord Webhooks)
- All backup scripts execute with `set -euo pipefail`.
- An active `trap 'on_error "$LINENO" "$BASH_COMMAND" "$?"' ERR` catches runtime failures immediately.
- Dispatches a Discord webhook embed with host identifier (`bjorn`), offending command, line number, exit code, and timestamp.

### 3.2 Passive Silence Detection (Dead Man's Snitch / Healthchecks.io)
- If cron fails or `bjorn` suffers kernel panic / power loss, active error traps cannot run.
- Successful backup runs signal a Healthchecks.io ping:
  ```bash
  curl -fsS -m 10 --retry 3 "${HEALTHCHECK_PING_URL}"
  ```
- If a daily ping is not received within the 25-hour window, Healthchecks.io fires an alert.

### 3.3 Storage Lifecycle & B2 Retention
- **Target Bucket**: Backblaze B2 `secure-backup` (or `jacobmiller22-secure-backup`).
- **Archive Format**: `backups/<service>/<service>-backup-%Y-%m-%d_%H-%M-%S.tar.gz.enc`.
- Non-destructive timestamps ensure daily archives never overwrite previous restore points.
- Backblaze B2 lifecycle rule enforces automated 30-day retention.

---

## 4. Disaster Recovery Validation Testing

The test harness `tools/backup-runner/test-backup-restore.sh` validates end-to-end backup, encryption, decryption, and SQLite integrity:

```bash
# Run local test suite on synthetic fixtures
bash tools/backup-runner/test-backup-restore.sh
```
