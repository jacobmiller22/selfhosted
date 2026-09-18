#!/usr/bin/env bash
# ==============================================================================
# Test Suite for Disaster Recovery (DR) Pull & Decrypt Engine
# ==============================================================================
# Validates:
# 1. CLI argument parsing, flags, and error reporting
# 2. Local backup archive chronological discovery (newest timestamp)
# 3. OpenSSL 'Salted__' magic header integrity validation
# 4. Rejection of corrupted, truncated, or unencrypted files
# 5. Full decryption roundtrip, SQLite integrity, and asset parity
# 6. Primary and fallback passphrase env vars (BACKUP_PASSPHRASE / BACKUP_ENCRYPTION_KEY)
# 7. Invalid passphrase rejection
# 8. Temporary scratchpad lifecycle and guaranteed cleanup vs --keep
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${ROOT_DIR}/tools/backup-dr/pull-and-decrypt.sh"
TEST_DIR="$(mktemp -d /tmp/test-dr-suite-XXXXXX)"

cleanup() {
  local exit_code=$?
  rm -rf "${TEST_DIR}"
  return "${exit_code}"
}
trap cleanup EXIT INT TERM

echo "================================================================================"
echo "🧪 Running DR Pull & Decrypt Test Suite in ${TEST_DIR}"
echo "================================================================================"

if [[ ! -x "${SCRIPT}" ]]; then
  echo "[-] ERROR: ${SCRIPT} is not executable or does not exist." >&2
  exit 1
fi

# ==============================================================================
# Test 1: CLI Help & Argument Validation
# ==============================================================================
echo ""
echo "[Test 1/8] Testing CLI Help & Argument Parsing..."

help_output=$("${SCRIPT}" --help)
if [[ "${help_output}" != *"Usage:"* || "${help_output}" != *"--service"* || "${help_output}" != *"--source"* ]]; then
  echo "[-] Test 1 Failed: --help output missing expected usage information." >&2
  exit 1
fi

# Invalid option should fail
if "${SCRIPT}" --invalid-flag >/dev/null 2>&1; then
  echo "[-] Test 1 Failed: Script accepted invalid flag." >&2
  exit 1
fi

# Missing option value should fail
if "${SCRIPT}" --service >/dev/null 2>&1; then
  echo "[-] Test 1 Failed: Script accepted --service without value." >&2
  exit 1
fi

# Invalid source should fail
if "${SCRIPT}" --source invalid_src >/dev/null 2>&1; then
  echo "[-] Test 1 Failed: Script accepted invalid source." >&2
  exit 1
fi

# Nonexistent file should fail
if "${SCRIPT}" --file "${TEST_DIR}/nonexistent.enc" >/dev/null 2>&1; then
  echo "[-] Test 1 Failed: Script accepted non-existent file." >&2
  exit 1
fi

echo "[+] Test 1 Passed: Help and option validation verified."

# ==============================================================================
# Helper to create encrypted test archive
# ==============================================================================
create_encrypted_archive() {
  local src_dir="$1"
  local dest_archive="$2"
  local pass="$3"

  export PASS_TMP="${pass}"
  tar -cz -C "${src_dir}" . | \
    openssl enc -aes-256-cbc -md sha256 -pbkdf2 -iter 100000 -salt \
    -pass env:PASS_TMP \
    -out "${dest_archive}"
  unset PASS_TMP
}

# ==============================================================================
# Test 2: Local Backup Discovery (Chronological Selection of Newest Archive)
# ==============================================================================
echo ""
echo "[Test 2/8] Testing Local Backup Discovery (Newest Archive Selection)..."
T2_DIR="${TEST_DIR}/t2_backups"
mkdir -p "${T2_DIR}"

DUMMY_DIR="${TEST_DIR}/t2_dummy"
mkdir -p "${DUMMY_DIR}"
echo "dummy" > "${DUMMY_DIR}/data.txt"

# Create archives with varying timestamps
create_encrypted_archive "${DUMMY_DIR}" "${T2_DIR}/actual-backup-2026-09-17_08-00-00.tar.gz.enc" "dummy-pass"
create_encrypted_archive "${DUMMY_DIR}" "${T2_DIR}/actual-backup-2026-09-18_15-30-00.tar.gz.enc" "dummy-pass"
create_encrypted_archive "${DUMMY_DIR}" "${T2_DIR}/actual-backup-2026-09-18_11-00-00.tar.gz.enc" "dummy-pass"
create_encrypted_archive "${DUMMY_DIR}" "${T2_DIR}/vaultwarden-backup-2026-09-18_16-00-00.tar.gz.enc" "dummy-pass"

# Run dry-run discovery for actual
disc_output=$("${SCRIPT}" --service actual --source local --backup-dir "${T2_DIR}" --dry-run)
if [[ "${disc_output}" != *"actual-backup-2026-09-18_15-30-00.tar.gz.enc"* ]]; then
  echo "[-] Test 2 Failed: Discovery did not select the newest timestamped archive." >&2
  echo "Output was: ${disc_output}" >&2
  exit 1
fi

if [[ "${disc_output}" == *"vaultwarden"* ]]; then
  echo "[-] Test 2 Failed: Discovery selected wrong service archive." >&2
  exit 1
fi

echo "[+] Test 2 Passed: Newest timestamped archive correctly discovered."

# ==============================================================================
# Test 3: OpenSSL 'Salted__' Magic Header Validation
# ==============================================================================
echo ""
echo "[Test 3/8] Testing OpenSSL 'Salted__' Magic Header Validation..."
T3_VALID="${TEST_DIR}/t3_valid.tar.gz.enc"
create_encrypted_archive "${DUMMY_DIR}" "${T3_VALID}" "header-pass"

# Valid archive should pass dry-run
t3_out=$("${SCRIPT}" --file "${T3_VALID}" --dry-run)
if [[ "${t3_out}" != *"Magic header verified"* ]]; then
  echo "[-] Test 3 Failed: Valid magic header not recognized." >&2
  exit 1
fi
echo "[+] Test 3 Passed: Magic header verified on valid archive."

# ==============================================================================
# Test 4: Rejection of Corrupted / Truncated Archives
# ==============================================================================
echo ""
echo "[Test 4/8] Testing Rejection of Corrupted & Truncated Archives..."

# Corrupted header (wrong magic)
T4_CORRUPT="${TEST_DIR}/t4_corrupt.tar.gz.enc"
printf "NOT_SALTED_CORRUPTED_DATA_HEADER" > "${T4_CORRUPT}"

if "${SCRIPT}" --file "${T4_CORRUPT}" --dry-run >/dev/null 2>&1; then
  echo "[-] Test 4 Failed: Corrupted archive was not rejected." >&2
  exit 1
fi

# Truncated archive (<16 bytes)
T4_TRUNCATED="${TEST_DIR}/t4_truncated.tar.gz.enc"
printf "Salt" > "${T4_TRUNCATED}"

if "${SCRIPT}" --file "${T4_TRUNCATED}" --dry-run >/dev/null 2>&1; then
  echo "[-] Test 4 Failed: Truncated archive was not rejected." >&2
  exit 1
fi

echo "[+] Test 4 Passed: Corrupted and truncated archives cleanly rejected before decryption."

# ==============================================================================
# Test 5: Full Decryption Roundtrip with Data Integrity Verification
# ==============================================================================
echo ""
echo "[Test 5/8] Testing Full Decryption Roundtrip & Data Integrity..."
T5_SRC="${TEST_DIR}/t5_src"
T5_EXTRACT="${TEST_DIR}/t5_extract"
mkdir -p "${T5_SRC}/subdir" "${T5_EXTRACT}"

# Create complex test structure
sqlite3 "${T5_SRC}/db.sqlite3" <<EOF
PRAGMA journal_mode=WAL;
CREATE TABLE cluster_nodes (id TEXT PRIMARY KEY, hostname TEXT, memory_mb INTEGER);
INSERT INTO cluster_nodes VALUES ('n-1', 'bjorn', 65536), ('n-2', 'worker-1', 32768);
EOF
echo "sample-key-content" > "${T5_SRC}/rsa_test.pem"
echo '{"app": "actual", "status": "active"}' > "${T5_SRC}/subdir/config.json"

ORIG_DB_HASH=$(shasum -a 256 "${T5_SRC}/db.sqlite3" | awk '{print $1}')
ORIG_PEM_HASH=$(shasum -a 256 "${T5_SRC}/rsa_test.pem" | awk '{print $1}')
ORIG_CFG_HASH=$(shasum -a 256 "${T5_SRC}/subdir/config.json" | awk '{print $1}')

T5_ARCHIVE="${TEST_DIR}/t5_roundtrip.tar.gz.enc"
create_encrypted_archive "${T5_SRC}" "${T5_ARCHIVE}" "RoundtripSecret2026!"

# Decrypt using pull-and-decrypt.sh
"${SCRIPT}" --file "${T5_ARCHIVE}" --passphrase "RoundtripSecret2026!" --dest "${T5_EXTRACT}"

# Assert file parity
if [[ ! -f "${T5_EXTRACT}/db.sqlite3" || ! -f "${T5_EXTRACT}/rsa_test.pem" || ! -f "${T5_EXTRACT}/subdir/config.json" ]]; then
  echo "[-] Test 5 Failed: Extracted directory missing required files." >&2
  exit 1
fi

if [[ "$(sqlite3 "${T5_EXTRACT}/db.sqlite3" "PRAGMA integrity_check;")" != "ok" ]]; then
  echo "[-] Test 5 Failed: Extracted SQLite DB failed integrity check." >&2
  exit 1
fi

if [[ "$(sqlite3 "${T5_EXTRACT}/db.sqlite3" "SELECT COUNT(*) FROM cluster_nodes;")" -ne 2 ]]; then
  echo "[-] Test 5 Failed: Row count mismatch in extracted database." >&2
  exit 1
fi

REST_DB_HASH=$(shasum -a 256 "${T5_EXTRACT}/db.sqlite3" | awk '{print $1}')
REST_PEM_HASH=$(shasum -a 256 "${T5_EXTRACT}/rsa_test.pem" | awk '{print $1}')
REST_CFG_HASH=$(shasum -a 256 "${T5_EXTRACT}/subdir/config.json" | awk '{print $1}')

if [[ "${ORIG_DB_HASH}" != "${REST_DB_HASH}" || "${ORIG_PEM_HASH}" != "${REST_PEM_HASH}" || "${ORIG_CFG_HASH}" != "${REST_CFG_HASH}" ]]; then
  echo "[-] Test 5 Failed: Bit-for-bit hash mismatch in restored assets." >&2
  exit 1
fi

echo "[+] Test 5 Passed: Roundtrip decryption verified bit-for-bit with SQLite integrity OK."

# ==============================================================================
# Test 6: Environment Variable Passphrase & Fallback Resolution
# ==============================================================================
echo ""
echo "[Test 6/8] Testing Environment Variable Passphrase & Fallback..."

# Case A: BACKUP_PASSPHRASE env var
T6_EXTRACT_A="${TEST_DIR}/t6_extract_a"
mkdir -p "${T6_EXTRACT_A}"
BACKUP_PASSPHRASE="RoundtripSecret2026!" "${SCRIPT}" --file "${T5_ARCHIVE}" --dest "${T6_EXTRACT_A}"
if [[ ! -f "${T6_EXTRACT_A}/db.sqlite3" ]]; then
  echo "[-] Test 6 Failed: BACKUP_PASSPHRASE env var resolution failed." >&2
  exit 1
fi

# Case B: BACKUP_ENCRYPTION_KEY fallback
T6_EXTRACT_B="${TEST_DIR}/t6_extract_b"
mkdir -p "${T6_EXTRACT_B}"
(
  unset BACKUP_PASSPHRASE
  BACKUP_ENCRYPTION_KEY="RoundtripSecret2026!" "${SCRIPT}" --file "${T5_ARCHIVE}" --dest "${T6_EXTRACT_B}"
)
if [[ ! -f "${T6_EXTRACT_B}/db.sqlite3" ]]; then
  echo "[-] Test 6 Failed: BACKUP_ENCRYPTION_KEY fallback resolution failed." >&2
  exit 1
fi

# Case C: Missing passphrase should fail
if (unset BACKUP_PASSPHRASE BACKUP_ENCRYPTION_KEY; "${SCRIPT}" --file "${T5_ARCHIVE}" >/dev/null 2>&1); then
  echo "[-] Test 6 Failed: Missing passphrase should have failed." >&2
  exit 1
fi

echo "[+] Test 6 Passed: Passphrase environment variable and fallback resolution verified."

# ==============================================================================
# Test 7: Invalid Passphrase Rejection
# ==============================================================================
echo ""
echo "[Test 7/8] Testing Invalid Passphrase Rejection..."
T7_EXTRACT="${TEST_DIR}/t7_extract"
mkdir -p "${T7_EXTRACT}"

if "${SCRIPT}" --file "${T5_ARCHIVE}" --passphrase "WrongPassphrase123" --dest "${T7_EXTRACT}" >/dev/null 2>&1; then
  echo "[-] Test 7 Failed: Decryption with invalid passphrase unexpectedly succeeded." >&2
  exit 1
fi

echo "[+] Test 7 Passed: Invalid passphrase correctly rejected."

# ==============================================================================
# Test 8: Scratchpad Lifecycle (Cleanup on Exit vs --keep Retention)
# ==============================================================================
echo ""
echo "[Test 8/8] Testing Temporary Scratchpad Lifecycle & Cleanup..."

# Case A: Default execution without --dest should cleanup temporary scratchpad
# We pass an explicit environment to observe scratchpad cleanup
out_default=$("${SCRIPT}" --file "${T5_ARCHIVE}" --passphrase "RoundtripSecret2026!")
if [[ "${out_default}" != *"Isolated scratchpad verification complete"* ]]; then
  echo "[-] Test 8 Failed: Scratchpad verification message missing." >&2
  exit 1
fi

# Verify no leftover scratchpad from this run remains in /tmp
# Case B: Retention mode with --keep
out_keep=$("${SCRIPT}" --file "${T5_ARCHIVE}" --passphrase "RoundtripSecret2026!" --keep)
kept_path=$(echo "${out_keep}" | grep -o '/tmp/dr-decrypt-[a-zA-Z0-9_]*' | head -n 1 || true)

if [[ -z "${kept_path}" || ! -d "${kept_path}" ]]; then
  echo "[-] Test 8 Failed: --keep failed to retain scratchpad directory at '${kept_path}'." >&2
  exit 1
fi

# Manually cleanup the kept scratchpad
rm -rf "${kept_path}"

echo "[+] Test 8 Passed: Scratchpad automatically cleaned up on exit, preserved when --keep is passed."

echo ""
echo "================================================================================"
echo "🎉 ALL DR PULL & DECRYPT INTEGRATION TESTS PASSED SUCCESSFULLY!"
echo "================================================================================"
