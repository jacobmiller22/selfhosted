#!/usr/bin/env bash
# ==============================================================================
# Comprehensive Backup & Restore Architecture Test Suite
# ==============================================================================
# Validates:
# 1. Generic OpenSSL AES-256-CBC PBKDF2 Roundtrip & Salted__ header
# 2. Declarative Engine: sqlite-auto mode (multi-DB, WAL journals, static assets)
# 3. Declarative Engine: filesystem mode (nested dirs, YAML/JSON configs, dotfiles)
# 4. Declarative Engine: hook mode (custom dump scripts e.g. PostgreSQL, CouchDB)
# 5. Staging directory lifecycle (guaranteed cleanup on success and error)
# 6. Fallback variable support (BACKUP_ENCRYPTION_KEY)
# 7. Actual Budget & Vaultwarden topology integration
# 8. Disaster Recovery (DR): Automated pull & decrypt engine integration
# 9. Automated Retention Policy, Remote Pruning & Safety Latch
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGINE_SCRIPT="${ROOT_DIR}/tools/backup-runner/backup-engine.sh"
TEST_DIR=$(mktemp -d /tmp/backup-suite-XXXXXX)
trap 'rm -rf "${TEST_DIR}"' EXIT

echo "================================================================================"
echo "🧪 Running Backup & Restore Test Suite in ${TEST_DIR}"
echo "================================================================================"

# ==============================================================================
# Test 1: Generic OpenSSL AES-256-CBC PBKDF2 Roundtrip
# ==============================================================================
echo ""
echo "[Test 1/9] Testing Generic OpenSSL AES-256-CBC PBKDF2 Roundtrip..."
T1_SRC="${TEST_DIR}/t1_src"
T1_EXTRACT="${TEST_DIR}/t1_extract"
mkdir -p "${T1_SRC}" "${T1_EXTRACT}"

sqlite3 "${T1_SRC}/test.sqlite" <<EOF
CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);
INSERT INTO items (name) VALUES ('item1'), ('item2');
EOF
echo "key_data" > "${T1_SRC}/key.pem"
echo "blob_data" > "${T1_SRC}/file.blob"

T1_PASSPHRASE="Test-Passphrase-12345"
T1_ARCHIVE="${TEST_DIR}/t1.tar.gz.enc"

export BACKUP_PASSPHRASE="${T1_PASSPHRASE}"
tar -cz -C "${T1_SRC}" . | \
  openssl enc -aes-256-cbc -md sha256 -pbkdf2 -iter 100000 -salt \
  -pass env:BACKUP_PASSPHRASE \
  -out "${T1_ARCHIVE}"

# Verify Salted__ header
if [[ "$(head -c 8 "${T1_ARCHIVE}")" != "Salted__" ]]; then
  echo "[-] Test 1 Failed: Archive missing OpenSSL Salted__ header" >&2
  exit 1
fi

# Decrypt using RESTORE.md procedure
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${T1_ARCHIVE}" \
  -pass env:BACKUP_PASSPHRASE | \
  tar -xz -C "${T1_EXTRACT}"

[[ "$(sqlite3 "${T1_EXTRACT}/test.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${T1_EXTRACT}/test.sqlite" "SELECT COUNT(*) FROM items;")" -eq 2 ]]
[[ "$(cat "${T1_EXTRACT}/key.pem")" == "key_data" ]]
[[ "$(cat "${T1_EXTRACT}/file.blob")" == "blob_data" ]]
echo "[+] Test 1 Passed: Generic roundtrip and OpenSSL header validated."

# ==============================================================================
# Test 2: Declarative Engine: sqlite-auto Strategy
# ==============================================================================
echo ""
echo "[Test 2/9] Testing Declarative Engine: sqlite-auto Strategy..."
T2_SRC="${TEST_DIR}/t2_src"
T2_EXTRACT="${TEST_DIR}/t2_extract"
T2_OUTPUT="${TEST_DIR}/t2_output"
mkdir -p "${T2_SRC}/db_subdir" "${T2_SRC}/assets" "${T2_EXTRACT}" "${T2_OUTPUT}"

# Database 1: Root sqlite file in WAL mode with active -wal and -shm
sqlite3 "${T2_SRC}/main.sqlite" <<EOF
PRAGMA journal_mode=WAL;
CREATE TABLE cluster (node_id TEXT PRIMARY KEY, role TEXT);
INSERT INTO cluster VALUES ('node-1', 'leader'), ('node-2', 'follower');
EOF
touch "${T2_SRC}/main.sqlite-wal"
touch "${T2_SRC}/main.sqlite-shm"

# Database 2: Nested sqlite3 database
sqlite3 "${T2_SRC}/db_subdir/app.sqlite3" <<EOF
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
INSERT INTO users (email) VALUES ('alice@example.com'), ('bob@example.com'), ('charlie@example.com');
EOF

# Database 3: .db extension
sqlite3 "${T2_SRC}/db_subdir/metrics.db" <<EOF
CREATE TABLE metrics (metric TEXT, val REAL);
INSERT INTO metrics VALUES ('cpu', 12.5), ('mem', 44.2);
EOF

# Assets: .blob, .pem, .json, and dotfiles
echo "binary_sync_blob_content" > "${T2_SRC}/assets/sync.blob"
echo "-----BEGIN PRIVATE KEY-----" > "${T2_SRC}/assets/server.pem"
echo '{"schema_version": 4}' > "${T2_SRC}/config.json"
echo 'migration_v4' > "${T2_SRC}/.migrate"

ORIG_BLOB_HASH=$(shasum -a 256 "${T2_SRC}/assets/sync.blob" | awk '{print $1}')
ORIG_PEM_HASH=$(shasum -a 256 "${T2_SRC}/assets/server.pem" | awk '{print $1}')
ORIG_JSON_HASH=$(shasum -a 256 "${T2_SRC}/config.json" | awk '{print $1}')
ORIG_MIGRATE_HASH=$(shasum -a 256 "${T2_SRC}/.migrate" | awk '{print $1}')

SERVICE_NAME="unified-sqlite-test" \
BACKUP_MODE="sqlite-auto" \
BACKUP_SOURCE_DIR="${T2_SRC}" \
BACKUP_PASSPHRASE="CanonicalEngineSecret2026" \
OUTPUT_DIR="${T2_OUTPUT}" \
"${ENGINE_SCRIPT}"

T2_ARCHIVE=$(find "${T2_OUTPUT}" -name "unified-sqlite-test-backup-*.tar.gz.enc" | head -n 1)
if [[ -z "${T2_ARCHIVE}" || ! -f "${T2_ARCHIVE}" ]]; then
  echo "[-] Test 2 Failed: sqlite-auto archive not created." >&2
  exit 1
fi

# Verify Salted__ header
if [[ "$(head -c 8 "${T2_ARCHIVE}")" != "Salted__" ]]; then
  echo "[-] Test 2 Failed: Archive missing OpenSSL Salted__ header" >&2
  exit 1
fi

# Decrypt using RESTORE.md procedure
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${T2_ARCHIVE}" \
  -pass pass:CanonicalEngineSecret2026 | \
  tar -xz -C "${T2_EXTRACT}"

# Verify no transient journal files are present
if find "${T2_EXTRACT}" -name "*-wal" -o -name "*-shm" -o -name "*-journal" | grep -q .; then
  echo "[-] Test 2 Failed: Transient journal files found in backup archive." >&2
  exit 1
fi

# Verify database integrity and data
[[ "$(sqlite3 "${T2_EXTRACT}/main.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${T2_EXTRACT}/main.sqlite" "SELECT COUNT(*) FROM cluster;")" -eq 2 ]]
[[ "$(sqlite3 "${T2_EXTRACT}/db_subdir/app.sqlite3" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${T2_EXTRACT}/db_subdir/app.sqlite3" "SELECT COUNT(*) FROM users;")" -eq 3 ]]
[[ "$(sqlite3 "${T2_EXTRACT}/db_subdir/metrics.db" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${T2_EXTRACT}/db_subdir/metrics.db" "SELECT COUNT(*) FROM metrics;")" -eq 2 ]]

# Verify assets bit-for-bit
[[ "$(shasum -a 256 "${T2_EXTRACT}/assets/sync.blob" | awk '{print $1}')" == "${ORIG_BLOB_HASH}" ]]
[[ "$(shasum -a 256 "${T2_EXTRACT}/assets/server.pem" | awk '{print $1}')" == "${ORIG_PEM_HASH}" ]]
[[ "$(shasum -a 256 "${T2_EXTRACT}/config.json" | awk '{print $1}')" == "${ORIG_JSON_HASH}" ]]
[[ "$(shasum -a 256 "${T2_EXTRACT}/.migrate" | awk '{print $1}')" == "${ORIG_MIGRATE_HASH}" ]]
echo "[+] Test 2 Passed: Declarative sqlite-auto mode validated cleanly."

# ==============================================================================
# Test 3: Declarative Engine: filesystem Strategy
# ==============================================================================
echo ""
echo "[Test 3/9] Testing Declarative Engine: filesystem Strategy..."
T3_SRC="${TEST_DIR}/t3_src"
T3_EXTRACT="${TEST_DIR}/t3_extract"
T3_OUTPUT="${TEST_DIR}/t3_output"
mkdir -p "${T3_SRC}/nested/conf" "${T3_SRC}/.storage" "${T3_EXTRACT}" "${T3_OUTPUT}"

echo "name: test-server" > "${T3_SRC}/config.yaml"
echo "port: 8080" > "${T3_SRC}/nested/conf/settings.yaml"
echo '{"token": "xyz123"}' > "${T3_SRC}/.storage/auth.json"

ORIG_YAML1_HASH=$(shasum -a 256 "${T3_SRC}/config.yaml" | awk '{print $1}')
ORIG_YAML2_HASH=$(shasum -a 256 "${T3_SRC}/nested/conf/settings.yaml" | awk '{print $1}')
ORIG_AUTH_HASH=$(shasum -a 256 "${T3_SRC}/.storage/auth.json" | awk '{print $1}')

SERVICE_NAME="unified-fs-test" \
BACKUP_MODE="filesystem" \
BACKUP_SOURCE_DIR="${T3_SRC}" \
BACKUP_PASSPHRASE="FileSystemSecret2026" \
OUTPUT_DIR="${T3_OUTPUT}" \
"${ENGINE_SCRIPT}"

T3_ARCHIVE=$(find "${T3_OUTPUT}" -name "unified-fs-test-backup-*.tar.gz.enc" | head -n 1)
if [[ -z "${T3_ARCHIVE}" || ! -f "${T3_ARCHIVE}" ]]; then
  echo "[-] Test 3 Failed: filesystem archive not created." >&2
  exit 1
fi

# Decrypt
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${T3_ARCHIVE}" \
  -pass pass:FileSystemSecret2026 | \
  tar -xz -C "${T3_EXTRACT}"

[[ "$(shasum -a 256 "${T3_EXTRACT}/config.yaml" | awk '{print $1}')" == "${ORIG_YAML1_HASH}" ]]
[[ "$(shasum -a 256 "${T3_EXTRACT}/nested/conf/settings.yaml" | awk '{print $1}')" == "${ORIG_YAML2_HASH}" ]]
[[ "$(shasum -a 256 "${T3_EXTRACT}/.storage/auth.json" | awk '{print $1}')" == "${ORIG_AUTH_HASH}" ]]
echo "[+] Test 3 Passed: Declarative filesystem mode validated cleanly."

# ==============================================================================
# Test 4: Declarative Engine: hook Strategy
# ==============================================================================
echo ""
echo "[Test 4/9] Testing Declarative Engine: hook Strategy..."
T4_HOOK="${TEST_DIR}/mock_pg_dump_hook.sh"
T4_EXTRACT="${TEST_DIR}/t4_extract"
T4_OUTPUT="${TEST_DIR}/t4_output"
mkdir -p "${T4_EXTRACT}" "${T4_OUTPUT}"

cat <<'EOF' > "${T4_HOOK}"
#!/usr/bin/env bash
set -euo pipefail
target_staging="$1"
mkdir -p "${target_staging}"
echo "-- Mock PostgreSQL Dump" > "${target_staging}/dump.sql"
echo "CREATE TABLE test (id int);" >> "${target_staging}/dump.sql"
echo '{"engine": "postgres", "version": "16.1"}' > "${target_staging}/metadata.json"
EOF
chmod +x "${T4_HOOK}"

SERVICE_NAME="unified-hook-test" \
BACKUP_MODE="hook" \
PRE_BACKUP_SCRIPT="${T4_HOOK}" \
BACKUP_PASSPHRASE="HookSecretPassphrase2026" \
OUTPUT_DIR="${T4_OUTPUT}" \
"${ENGINE_SCRIPT}"

T4_ARCHIVE=$(find "${T4_OUTPUT}" -name "unified-hook-test-backup-*.tar.gz.enc" | head -n 1)
if [[ -z "${T4_ARCHIVE}" || ! -f "${T4_ARCHIVE}" ]]; then
  echo "[-] Test 4 Failed: hook archive not created." >&2
  exit 1
fi

openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${T4_ARCHIVE}" \
  -pass pass:HookSecretPassphrase2026 | \
  tar -xz -C "${T4_EXTRACT}"

[[ -f "${T4_EXTRACT}/dump.sql" ]]
[[ -f "${T4_EXTRACT}/metadata.json" ]]
grep -q "Mock PostgreSQL Dump" "${T4_EXTRACT}/dump.sql"
grep -q '"engine": "postgres"' "${T4_EXTRACT}/metadata.json"
echo "[+] Test 4 Passed: Declarative hook mode validated cleanly."

# ==============================================================================
# Test 5: Safe Staging Directory Lifecycle (Cleanup on Success and Error)
# ==============================================================================
echo ""
echo "[Test 5/9] Testing Staging Directory Lifecycle (Cleanup on Success and Error)..."
# Part A: Cleanup on success
T5A_STAGING="${TEST_DIR}/t5a_staging"
T5A_SRC="${TEST_DIR}/t5a_src"
mkdir -p "${T5A_SRC}"
echo "file_data" > "${T5A_SRC}/file.txt"

STAGING_DIR="${T5A_STAGING}" \
SERVICE_NAME="cleanup-success" \
BACKUP_MODE="filesystem" \
BACKUP_SOURCE_DIR="${T5A_SRC}" \
BACKUP_PASSPHRASE="Pass123" \
OUTPUT_DIR="${TEST_DIR}/t5a_output" \
"${ENGINE_SCRIPT}" >/dev/null

if [[ -d "${T5A_STAGING}" ]]; then
  echo "[-] Test 5 Failed: Staging directory ${T5A_STAGING} was not cleaned up after success!" >&2
  exit 1
fi
echo "[+] Staging directory successfully cleaned up after normal execution."

# Part B: Cleanup on error
T5B_STAGING="${TEST_DIR}/t5b_staging"
T5B_FAIL_HOOK="${TEST_DIR}/fail_hook.sh"
cat <<'EOF' > "${T5B_FAIL_HOOK}"
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$1/leaked_dir"
echo "dirty data" > "$1/leaked_dir/dirty.txt"
echo "Simulating failure during dump" >&2
exit 42
EOF
chmod +x "${T5B_FAIL_HOOK}"

set +e
STAGING_DIR="${T5B_STAGING}" \
SERVICE_NAME="cleanup-fail" \
BACKUP_MODE="hook" \
PRE_BACKUP_SCRIPT="${T5B_FAIL_HOOK}" \
BACKUP_PASSPHRASE="Pass123" \
OUTPUT_DIR="${TEST_DIR}/t5b_output" \
"${ENGINE_SCRIPT}" >/dev/null 2>&1
T5B_EXIT=$?
set -e

if [[ "${T5B_EXIT}" -ne 42 ]]; then
  echo "[-] Test 5 Failed: Expected exit code 42 on failure, got ${T5B_EXIT}" >&2
  exit 1
fi

if [[ -d "${T5B_STAGING}" ]]; then
  echo "[-] Test 5 Failed: Staging directory ${T5B_STAGING} was not cleaned up after error!" >&2
  exit 1
fi
echo "[+] Staging directory successfully cleaned up after failure (exit code 42 preserved)."
echo "[+] Test 5 Passed: Guaranteed staging lifecycle verified on success and error."

# ==============================================================================
# Test 6: Fallback Variable Support (BACKUP_ENCRYPTION_KEY)
# ==============================================================================
echo ""
echo "[Test 6/9] Testing Fallback Variable Support (BACKUP_ENCRYPTION_KEY)..."
T6_SRC="${TEST_DIR}/t6_src"
T6_EXTRACT="${TEST_DIR}/t6_extract"
T6_OUTPUT="${TEST_DIR}/t6_output"
mkdir -p "${T6_SRC}" "${T6_EXTRACT}" "${T6_OUTPUT}"
echo "fallback_key_content" > "${T6_SRC}/data.txt"

unset BACKUP_PASSPHRASE
SERVICE_NAME="fallback-key-test" \
BACKUP_MODE="filesystem" \
BACKUP_SOURCE_DIR="${T6_SRC}" \
BACKUP_ENCRYPTION_KEY="LegacyFallbackKey2026" \
OUTPUT_DIR="${T6_OUTPUT}" \
"${ENGINE_SCRIPT}" >/dev/null

T6_ARCHIVE=$(find "${T6_OUTPUT}" -name "fallback-key-test-backup-*.tar.gz.enc" | head -n 1)
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${T6_ARCHIVE}" \
  -pass pass:LegacyFallbackKey2026 | \
  tar -xz -C "${T6_EXTRACT}"

[[ "$(cat "${T6_EXTRACT}/data.txt")" == "fallback_key_content" ]]
echo "[+] Test 6 Passed: BACKUP_ENCRYPTION_KEY fallback supported cleanly."

# ==============================================================================
# Test 7: Actual Budget & Vaultwarden Integration Topology
# ==============================================================================
echo ""
echo "[Test 7/9] Testing Actual Budget & Vaultwarden Topology Integration..."

# Actual Budget Topology
ACTUAL_DATA="${TEST_DIR}/actual-data"
ACTUAL_EXTRACT="${TEST_DIR}/actual-extract"
ACTUAL_OUTPUT="${TEST_DIR}/actual-output"
mkdir -p "${ACTUAL_DATA}/server-files" "${ACTUAL_DATA}/user-files" "${ACTUAL_EXTRACT}" "${ACTUAL_OUTPUT}"

sqlite3 "${ACTUAL_DATA}/server-files/account.sqlite" "CREATE TABLE users (id TEXT PRIMARY KEY); INSERT INTO users VALUES ('u1');"
sqlite3 "${ACTUAL_DATA}/user-files/group-1.sqlite" "PRAGMA journal_mode=WAL; CREATE TABLE t (id TEXT); INSERT INTO t VALUES ('t1');"
touch "${ACTUAL_DATA}/user-files/group-1.sqlite-wal"
touch "${ACTUAL_DATA}/user-files/group-1.sqlite-shm"
echo "blob1" > "${ACTUAL_DATA}/user-files/f1.blob"
echo '{"version": 17}' > "${ACTUAL_DATA}/.migrate"

SERVICE_NAME="actual" \
BACKUP_MODE="sqlite-auto" \
BACKUP_SOURCE_DIR="${ACTUAL_DATA}" \
BACKUP_PASSPHRASE="ActualPassphrase2026" \
OUTPUT_DIR="${ACTUAL_OUTPUT}" \
"${ENGINE_SCRIPT}" >/dev/null

ACTUAL_ARCHIVE=$(find "${ACTUAL_OUTPUT}" -name "actual-backup-*.tar.gz.enc" | head -n 1)
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${ACTUAL_ARCHIVE}" \
  -pass pass:ActualPassphrase2026 | \
  tar -xz -C "${ACTUAL_EXTRACT}"

[[ "$(sqlite3 "${ACTUAL_EXTRACT}/server-files/account.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${ACTUAL_EXTRACT}/user-files/group-1.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(cat "${ACTUAL_EXTRACT}/user-files/f1.blob")" == "blob1" ]]
[[ "$(cat "${ACTUAL_EXTRACT}/.migrate")" == '{"version": 17}' ]]

# Vaultwarden Topology
VW_DATA="${TEST_DIR}/vw-data"
VW_EXTRACT="${TEST_DIR}/vw-extract"
VW_OUTPUT="${TEST_DIR}/vw-output"
mkdir -p "${VW_DATA}/attachments" "${VW_DATA}/sends" "${VW_EXTRACT}" "${VW_OUTPUT}"

sqlite3 "${VW_DATA}/db.sqlite3" "PRAGMA journal_mode=WAL; CREATE TABLE c (id TEXT); INSERT INTO c VALUES ('c1');"
touch "${VW_DATA}/db.sqlite3-wal"
touch "${VW_DATA}/db.sqlite3-shm"
echo "key_data" > "${VW_DATA}/rsa_key.pem"
echo "att_data" > "${VW_DATA}/attachments/a1.bin"
echo "send_data" > "${VW_DATA}/sends/s1.json"
echo '{"signups": false}' > "${VW_DATA}/config.json"

SERVICE_NAME="vaultwarden" \
BACKUP_MODE="sqlite-auto" \
BACKUP_SOURCE_DIR="${VW_DATA}" \
BACKUP_PASSPHRASE="VaultwardenPassphrase2026" \
OUTPUT_DIR="${VW_OUTPUT}" \
"${ENGINE_SCRIPT}" >/dev/null

VW_ARCHIVE=$(find "${VW_OUTPUT}" -name "vaultwarden-backup-*.tar.gz.enc" | head -n 1)
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${VW_ARCHIVE}" \
  -pass pass:VaultwardenPassphrase2026 | \
  tar -xz -C "${VW_EXTRACT}"

[[ "$(sqlite3 "${VW_EXTRACT}/db.sqlite3" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(cat "${VW_EXTRACT}/rsa_key.pem")" == "key_data" ]]
[[ "$(cat "${VW_EXTRACT}/attachments/a1.bin")" == "att_data" ]]
[[ "$(cat "${VW_EXTRACT}/sends/s1.json")" == "send_data" ]]
[[ "$(cat "${VW_EXTRACT}/config.json")" == '{"signups": false}' ]]
echo "[+] Test 7 Passed: Actual Budget and Vaultwarden topologies backed up and restored cleanly."

# ==============================================================================
# Test 8: Disaster Recovery (DR) Automated Pull & Decrypt Engine Integration
# ==============================================================================
echo ""
echo "[Test 8/9] Testing Disaster Recovery (DR) Pull & Decrypt Engine..."
DR_SCRIPT="${ROOT_DIR}/tools/backup-dr/pull-and-decrypt.sh"
DR_TEST_SUITE="${ROOT_DIR}/tools/backup-dr/test-dr-pull-decrypt.sh"

# 1. Decrypt Actual archive produced by declarative engine via pull-and-decrypt.sh
DR_ACTUAL_EXTRACT="${TEST_DIR}/dr-actual-extract"
mkdir -p "${DR_ACTUAL_EXTRACT}"

"${DR_SCRIPT}" \
  --service actual \
  --source local \
  --backup-dir "${ACTUAL_OUTPUT}" \
  --passphrase "ActualPassphrase2026" \
  --dest "${DR_ACTUAL_EXTRACT}"

[[ "$(sqlite3 "${DR_ACTUAL_EXTRACT}/server-files/account.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${DR_ACTUAL_EXTRACT}/user-files/group-1.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(cat "${DR_ACTUAL_EXTRACT}/user-files/f1.blob")" == "blob1" ]]
[[ "$(cat "${DR_ACTUAL_EXTRACT}/.migrate")" == '{"version": 17}' ]]

# 2. Dry-run verification on Vaultwarden output
"${DR_SCRIPT}" \
  --service vaultwarden \
  --source local \
  --backup-dir "${VW_OUTPUT}" \
  --dry-run

# 3. Execute standalone DR test harness
"${DR_TEST_SUITE}"

echo "[+] Test 8 Passed: Disaster Recovery pull & decrypt engine validated end-to-end."

# ==============================================================================
# Test 9: Automated Retention Policy, Remote Pruning & Safety Latch
# ==============================================================================
echo ""
echo "[Test 9/9] Testing Automated Retention Policy, Remote Pruning & Safety Latch..."

# Part A: CLI Help & Option Validation
HELP_OUT=$("${ENGINE_SCRIPT}" --help)
if [[ "${HELP_OUT}" != *"--retention-days"* || "${HELP_OUT}" != *"--dry-run"* || "${HELP_OUT}" != *"--b2-dest-path"* ]]; then
  echo "[-] Test 9 Failed: --help output missing retention or dry-run options" >&2
  exit 1
fi

# Part B: Invalid BACKUP_RETENTION_DAYS rejection
set +e
INV_RES=$(BACKUP_RETENTION_DAYS=0 "${ENGINE_SCRIPT}" 2>&1)
INV_EXIT=$?
set -e
if [[ "${INV_EXIT}" -eq 0 || "${INV_RES}" != *"Invalid BACKUP_RETENTION_DAYS"* ]]; then
  echo "[-] Test 9 Failed: Invalid BACKUP_RETENTION_DAYS=0 was not rejected cleanly" >&2
  exit 1
fi

# Part C: Safety Latch Abort (when upload is unverified)
set +e
LATCH_RES=$("${ENGINE_SCRIPT}" --prune-only 2>&1)
LATCH_EXIT=$?
set -e
if [[ "${LATCH_EXIT}" -eq 0 || "${LATCH_RES}" != *"SAFETY ABORT"* ]]; then
  echo "[-] Test 9 Failed: Safety latch did not abort unverified pruning" >&2
  exit 1
fi
echo "[+] Safety latch successfully prevented pruning without verified upload."

# Part D: Mock rclone Pruning & Dry-Run Verification
T9_BIN="${TEST_DIR}/t9_bin"
mkdir -p "${T9_BIN}"
RCLONE_MOCK_LOG="${TEST_DIR}/rclone_mock.log"

cat <<'EOF' > "${T9_BIN}/rclone"
#!/usr/bin/env bash
echo "$*" >> "${RCLONE_LOG_FILE}"
cmd="$1"
case "${cmd}" in
  lsl)
    echo "  10240 2026-08-01 12:00:00.000000000 test-backup-2026-08-01_12-00-00.tar.gz.enc"
    echo "  20480 2026-08-10 12:00:00.000000000 test-backup-2026-08-10_12-00-00.tar.gz.enc"
    ;;
  lsf|copyto|delete|cleanup)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
chmod +x "${T9_BIN}/rclone"

# Test Dry-Run simulation with 45-day retention
export RCLONE_LOG_FILE="${RCLONE_MOCK_LOG}"
: > "${RCLONE_MOCK_LOG}"

PATH="${T9_BIN}:${PATH}" \
BACKUP_UPLOAD_VERIFIED=true \
SERVICE_NAME="retention-dryrun" \
B2_DEST_PATH="b2:mybucket/backups/retention-dryrun" \
BACKUP_RETENTION_DAYS=45 \
DRY_RUN=true \
"${ENGINE_SCRIPT}" --prune-only >/dev/null

if ! grep -q "delete b2:mybucket/backups/retention-dryrun.*--min-age 45d.*--dry-run" "${RCLONE_MOCK_LOG}"; then
  echo "[-] Test 9 Failed: rclone delete was not called with --min-age 45d and --dry-run" >&2
  exit 1
fi
if ! grep -q "cleanup b2:mybucket/backups/retention-dryrun.*--dry-run" "${RCLONE_MOCK_LOG}"; then
  echo "[-] Test 9 Failed: rclone cleanup was not called with --dry-run" >&2
  exit 1
fi
echo "[+] Dry-run simulation with custom retention verified."

# Test Live Pruning execution with 30-day retention
: > "${RCLONE_MOCK_LOG}"

PATH="${T9_BIN}:${PATH}" \
BACKUP_UPLOAD_VERIFIED=true \
SERVICE_NAME="retention-live" \
B2_DEST_PATH="b2:mybucket/backups/retention-live" \
BACKUP_RETENTION_DAYS=30 \
DRY_RUN=false \
"${ENGINE_SCRIPT}" --prune-only >/dev/null

if ! grep -q "delete b2:mybucket/backups/retention-live.*--min-age 30d" "${RCLONE_MOCK_LOG}"; then
  echo "[-] Test 9 Failed: rclone delete was not called with --min-age 30d" >&2
  exit 1
fi
if grep -q "delete.*--dry-run" "${RCLONE_MOCK_LOG}"; then
  echo "[-] Test 9 Failed: rclone delete unexpectedly received --dry-run in live mode" >&2
  exit 1
fi
if ! grep -q "cleanup b2:mybucket/backups/retention-live" "${RCLONE_MOCK_LOG}"; then
  echo "[-] Test 9 Failed: rclone cleanup was not called on target remote" >&2
  exit 1
fi
echo "[+] Live pruning execution and rclone cleanup verified."

# Part E: End-to-End Safety Ordering (Upload failure aborts before pruning)
: > "${RCLONE_MOCK_LOG}"
T9_FAIL_BIN="${TEST_DIR}/t9_fail_bin"
mkdir -p "${T9_FAIL_BIN}"
cat <<'EOF' > "${T9_FAIL_BIN}/rclone"
#!/usr/bin/env bash
echo "$*" >> "${RCLONE_LOG_FILE}"
cmd="$1"
case "${cmd}" in
  copyto)
    echo "Simulated network failure on cloud upload" >&2
    exit 1
    ;;
  *)
    exit 0
    ;;
esac
EOF
chmod +x "${T9_FAIL_BIN}/rclone"

T9_SRC="${TEST_DIR}/t9_src"
mkdir -p "${T9_SRC}"
echo "sample_data" > "${T9_SRC}/data.txt"

set +e
PATH="${T9_FAIL_BIN}:${PATH}" \
SERVICE_NAME="safety-ordering" \
BACKUP_MODE="filesystem" \
BACKUP_SOURCE_DIR="${T9_SRC}" \
BACKUP_PASSPHRASE="TestKey" \
B2_DEST_PATH="b2:mybucket/backups/safety-ordering" \
OUTPUT_DIR="${TEST_DIR}/t9_out" \
"${ENGINE_SCRIPT}" >/dev/null 2>&1
T9_FAIL_EXIT=$?
set -e

if [[ "${T9_FAIL_EXIT}" -eq 0 ]]; then
  echo "[-] Test 9 Failed: Backup engine should have failed when upload failed" >&2
  exit 1
fi

if grep -q "delete" "${RCLONE_MOCK_LOG}"; then
  echo "[-] Test 9 Failed: rclone delete was called despite failed upload! Safety latch violated." >&2
  exit 1
fi
echo "[+] End-to-end safety ordering verified: upload failure prevented pruning."

echo "[+] Test 9 Passed: Automated retention, remote pruning, and safety latch verified end-to-end."

echo ""
echo "================================================================================"
echo "🎉 ALL BACKUP & RESTORE ARCHITECTURE TESTS PASSED SUCCESSFULLY!"
echo "================================================================================"
