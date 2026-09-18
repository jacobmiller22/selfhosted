#!/usr/bin/env bash
# ==============================================================================
# Disaster Recovery (DR): Database & Storage Integrity Test Suite
# ==============================================================================
# Integration tests validating tools/backup-dr/verify-db-integrity.sh:
# - CLI arguments, options, and help flag behavior
# - SQLite page integrity and foreign key constraint verification
# - Actual Budget account, user databases, and sync blobs
# - Vaultwarden DB, RSA 0600 key permissions, and storage directories
# - Home Assistant DB and .storage/* JSON registry validation
# - Nginx Proxy Manager DB and Let's Encrypt certificate inspection
# - PostgreSQL dump header signatures and table count assertions
# - Precise structured exit codes for all failure scenarios
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_SCRIPT="${SCRIPT_DIR}/verify-db-integrity.sh"

if [[ ! -x "${VERIFY_SCRIPT}" ]]; then
  echo "[-] ERROR: Target script ${VERIFY_SCRIPT} is not executable." >&2
  exit 1
fi

TEST_SANDBOX="$(mktemp -d /tmp/dr-integrity-test-XXXXXX)"
cleanup() {
  local exit_code=$?
  rm -rf "${TEST_SANDBOX}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

echo "================================================================================"
echo "🧪 Running Database & Storage DR Integrity Test Suite"
echo "Sandbox: ${TEST_SANDBOX}"
echo "================================================================================"

# ==============================================================================
# Test 1: CLI Flags & Input Validation
# ==============================================================================
echo ""
echo "[Test 1/8] CLI Argument & Flag Validation..."

# Help flags
"${VERIFY_SCRIPT}" -h >/dev/null
"${VERIFY_SCRIPT}" --help >/dev/null

# Missing directory and file argument
if "${VERIFY_SCRIPT}" >/dev/null 2>&1; then
  echo "[-] Test 1 Failed: Running without --dir or --file should exit nonzero." >&2
  exit 1
fi

# Nonexistent directory
if "${VERIFY_SCRIPT}" --dir "${TEST_SANDBOX}/nonexistent" >/dev/null 2>&1; then
  echo "[-] Test 1 Failed: Nonexistent directory should fail." >&2
  exit 1
fi

# Missing argument value
if "${VERIFY_SCRIPT}" --service >/dev/null 2>&1; then
  echo "[-] Test 1 Failed: Missing value for --service should fail." >&2
  exit 1
fi

echo "[+] Test 1 Passed: CLI arguments and help flags behave correctly."

# ==============================================================================
# Test 2: Actual Budget Integrity & Sanity Verification
# ==============================================================================
echo ""
echo "[Test 2/8] Actual Budget Integrity & Assertions..."
ACTUAL_DIR="${TEST_SANDBOX}/actual_payload"
mkdir -p "${ACTUAL_DIR}/server-files" "${ACTUAL_DIR}/user-files"

# Create valid account.sqlite
sqlite3 "${ACTUAL_DIR}/server-files/account.sqlite" <<'EOF'
PRAGMA foreign_keys = ON;
CREATE TABLE users (id TEXT PRIMARY KEY, user_name TEXT);
INSERT INTO users VALUES ('usr_1', 'admin@example.com');
EOF

# Create valid user budget database
sqlite3 "${ACTUAL_DIR}/user-files/budget1.sqlite" <<'EOF'
PRAGMA foreign_keys = ON;
CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE transactions (id TEXT PRIMARY KEY, acct_id TEXT REFERENCES accounts(id), amount INT);
INSERT INTO accounts VALUES ('acct_1', 'Checking');
INSERT INTO transactions VALUES ('tx_1', 'acct_1', -5000);
EOF

# Create client-side sync blob
echo "mock_client_sync_blob_payload" > "${ACTUAL_DIR}/user-files/sync.blob"

# Run verification (should succeed)
"${VERIFY_SCRIPT}" --service actual --dir "${ACTUAL_DIR}" --verbose

# Sub-test 2a: Zero users in account.sqlite (should fail with exit code 4)
sqlite3 "${ACTUAL_DIR}/server-files/account.sqlite" "DELETE FROM users;"
set +e
"${VERIFY_SCRIPT}" --service actual --dir "${ACTUAL_DIR}" >/dev/null 2>&1
res_empty_users=$?
set -e
if [[ "${res_empty_users}" -ne 4 ]]; then
  echo "[-] Test 2a Failed: Zero users should exit with code 4, got ${res_empty_users}" >&2
  exit 1
fi

# Restore user
sqlite3 "${ACTUAL_DIR}/server-files/account.sqlite" "INSERT INTO users VALUES ('usr_1', 'admin@example.com');"

# Sub-test 2b: Foreign key violation in user budget database (should fail with exit code 3)
sqlite3 "${ACTUAL_DIR}/user-files/budget1.sqlite" "PRAGMA foreign_keys = OFF; INSERT INTO transactions VALUES ('tx_orphan', 'nonexistent_account', 100);"
set +e
"${VERIFY_SCRIPT}" --service actual --dir "${ACTUAL_DIR}" >/dev/null 2>&1
res_fk_fail=$?
set -e
if [[ "${res_fk_fail}" -ne 3 ]]; then
  echo "[-] Test 2b Failed: FK violation should exit with code 3, got ${res_fk_fail}" >&2
  exit 1
fi

# Fix FK violation
sqlite3 "${ACTUAL_DIR}/user-files/budget1.sqlite" "DELETE FROM transactions WHERE id = 'tx_orphan';"

# Sub-test 2c: Missing .blob file (should fail with exit code 6)
rm "${ACTUAL_DIR}/user-files/sync.blob"
set +e
"${VERIFY_SCRIPT}" --service actual --dir "${ACTUAL_DIR}" >/dev/null 2>&1
res_missing_blob=$?
set -e
if [[ "${res_missing_blob}" -ne 6 ]]; then
  echo "[-] Test 2c Failed: Missing blob should exit with code 6, got ${res_missing_blob}" >&2
  exit 1
fi

# Restore blob
echo "blob_data" > "${ACTUAL_DIR}/user-files/sync.blob"

# Sub-test 2d: Empty (0-byte) .blob file (should fail with exit code 6)
: > "${ACTUAL_DIR}/user-files/sync.blob"
set +e
"${VERIFY_SCRIPT}" --service actual --dir "${ACTUAL_DIR}" >/dev/null 2>&1
res_empty_blob=$?
set -e
if [[ "${res_empty_blob}" -ne 6 ]]; then
  echo "[-] Test 2d Failed: Empty blob should exit with code 6, got ${res_empty_blob}" >&2
  exit 1
fi

echo "[+] Test 2 Passed: Actual Budget assertions, FK validation, and blob checks verified."

# ==============================================================================
# Test 3: Vaultwarden Integrity, Cryptography & Directory Checks
# ==============================================================================
echo ""
echo "[Test 3/8] Vaultwarden DB, Cryptography & Storage..."
VW_DIR="${TEST_SANDBOX}/vaultwarden_payload"
mkdir -p "${VW_DIR}/attachments" "${VW_DIR}/sends"

# Create valid db.sqlite3
sqlite3 "${VW_DIR}/db.sqlite3" <<'EOF'
PRAGMA foreign_keys = ON;
CREATE TABLE users (uuid TEXT PRIMARY KEY, email TEXT);
CREATE TABLE ciphers (uuid TEXT PRIMARY KEY, user_uuid TEXT REFERENCES users(uuid), notes TEXT);
INSERT INTO users VALUES ('u-1', 'admin@example.com');
INSERT INTO ciphers VALUES ('c-1', 'u-1', 'sample-encrypted-vault-item');
EOF

# Create valid RSA private key
openssl genrsa -out "${VW_DIR}/rsa_key.pem" 2048 2>/dev/null
chmod 600 "${VW_DIR}/rsa_key.pem"

# Run verification (should succeed)
"${VERIFY_SCRIPT}" --service vaultwarden --dir "${VW_DIR}" --verbose

# Sub-test 3a: Permissive key permissions 0644 (should fail with exit code 5)
chmod 644 "${VW_DIR}/rsa_key.pem"
set +e
"${VERIFY_SCRIPT}" --service vaultwarden --dir "${VW_DIR}" >/dev/null 2>&1
res_bad_perms=$?
set -e
if [[ "${res_bad_perms}" -ne 5 ]]; then
  echo "[-] Test 3a Failed: Permissive rsa_key.pem permissions should exit code 5, got ${res_bad_perms}" >&2
  exit 1
fi
chmod 600 "${VW_DIR}/rsa_key.pem"

# Sub-test 3b: Corrupted RSA private key content (should fail with exit code 5)
echo "-----BEGIN RSA PRIVATE KEY-----" > "${VW_DIR}/rsa_key.pem"
echo "CORRUPTED_KEY_DATA_INVALID_BASE64" >> "${VW_DIR}/rsa_key.pem"
echo "-----END RSA PRIVATE KEY-----" >> "${VW_DIR}/rsa_key.pem"
set +e
"${VERIFY_SCRIPT}" --service vaultwarden --dir "${VW_DIR}" >/dev/null 2>&1
res_bad_key=$?
set -e
if [[ "${res_bad_key}" -ne 5 ]]; then
  echo "[-] Test 3b Failed: Corrupt rsa_key.pem should exit code 5, got ${res_bad_key}" >&2
  exit 1
fi

# Restore valid RSA key
openssl genrsa -out "${VW_DIR}/rsa_key.pem" 2048 2>/dev/null
chmod 600 "${VW_DIR}/rsa_key.pem"

# Sub-test 3c: Missing sends/ directory (should fail with exit code 6)
rmdir "${VW_DIR}/sends"
set +e
"${VERIFY_SCRIPT}" --service vaultwarden --dir "${VW_DIR}" >/dev/null 2>&1
res_missing_sends=$?
set -e
if [[ "${res_missing_sends}" -ne 6 ]]; then
  echo "[-] Test 3c Failed: Missing sends directory should exit code 6, got ${res_missing_sends}" >&2
  exit 1
fi
mkdir -p "${VW_DIR}/sends"

echo "[+] Test 3 Passed: Vaultwarden cryptographic and storage checks verified."

# ==============================================================================
# Test 4: Home Assistant DB & .storage/* JSON Registries
# ==============================================================================
echo ""
echo "[Test 4/8] Home Assistant DB & JSON Registries..."
HA_DIR="${TEST_SANDBOX}/ha_payload"
mkdir -p "${HA_DIR}/.storage"

# Create valid DB
sqlite3 "${HA_DIR}/home-assistant_v2.db" <<'EOF'
CREATE TABLE states (state_id INTEGER PRIMARY KEY, entity_id TEXT, state TEXT);
INSERT INTO states VALUES (1, 'sensor.temperature', '72.0');
EOF

# Create valid JSON registries in .storage
echo '{"version": 1, "key": "core.config", "data": {"latitude": 40.71, "longitude": -74.00}}' > "${HA_DIR}/.storage/core.config"
echo '{"version": 1, "key": "auth", "data": {"users": [{"id": "ha_admin"}]}}' > "${HA_DIR}/.storage/auth"

# Verification should succeed
"${VERIFY_SCRIPT}" --service homeassistant --dir "${HA_DIR}" --verbose

# Sub-test 4a: Corrupted / invalid JSON in .storage
echo '{"version": 1, "unclosed_brace": true' > "${HA_DIR}/.storage/corrupt.json"
set +e
"${VERIFY_SCRIPT}" --service homeassistant --dir "${HA_DIR}" >/dev/null 2>&1
res_bad_json=$?
set -e
if [[ "${res_bad_json}" -ne 7 ]]; then
  echo "[-] Test 4a Failed: Corrupt JSON should exit code 7, got ${res_bad_json}" >&2
  exit 1
fi
rm "${HA_DIR}/.storage/corrupt.json"

echo "[+] Test 4 Passed: Home Assistant database and JSON registries verified."

# ==============================================================================
# Test 5: Nginx Proxy Manager DB & Certificates
# ==============================================================================
echo ""
echo "[Test 5/8] Nginx Proxy Manager & SSL Certificates..."
NPM_DIR="${TEST_SANDBOX}/npm_payload"
mkdir -p "${NPM_DIR}/letsencrypt"

sqlite3 "${NPM_DIR}/database.sqlite" <<'EOF'
CREATE TABLE proxy_host (id INTEGER PRIMARY KEY, domain_names TEXT, forward_host TEXT);
INSERT INTO proxy_host VALUES (1, '["actual.cloud.jacobmiller22.com"]', 'actual_server');
EOF

# Generate self-signed cert
openssl req -x509 -newkey rsa:2048 -nodes -keyout "${NPM_DIR}/letsencrypt/privkey.pem" \
  -out "${NPM_DIR}/letsencrypt/cert.pem" -days 30 -subj "/CN=cloud.jacobmiller22.com" 2>/dev/null

"${VERIFY_SCRIPT}" --service npm --dir "${NPM_DIR}" --verbose

# Sub-test 5a: Invalid/truncated certificate
echo "-----BEGIN CERTIFICATE-----" > "${NPM_DIR}/letsencrypt/broken_cert.pem"
echo "TRUNCATED_CERTIFICATE_DATA" >> "${NPM_DIR}/letsencrypt/broken_cert.pem"
echo "-----END CERTIFICATE-----" >> "${NPM_DIR}/letsencrypt/broken_cert.pem"
set +e
"${VERIFY_SCRIPT}" --service npm --dir "${NPM_DIR}" >/dev/null 2>&1
res_bad_cert=$?
set -e
if [[ "${res_bad_cert}" -ne 5 ]]; then
  echo "[-] Test 5a Failed: Truncated cert should exit code 5, got ${res_bad_cert}" >&2
  exit 1
fi
rm "${NPM_DIR}/letsencrypt/broken_cert.pem"

echo "[+] Test 5 Passed: Nginx Proxy Manager database and certificate checks verified."

# ==============================================================================
# Test 6: PostgreSQL Dump Assertions
# ==============================================================================
echo ""
echo "[Test 6/8] PostgreSQL Dump Assertions..."
PG_DIR="${TEST_SANDBOX}/pg_payload"
mkdir -p "${PG_DIR}"

cat <<'EOF' > "${PG_DIR}/dump.sql"
--
-- PostgreSQL database dump
-- Dumped by pg_dump version 16.1
--
SET statement_timeout = 0;
CREATE TABLE cluster_services (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL);
CREATE TABLE metrics (id SERIAL PRIMARY KEY, cpu_percent REAL);
INSERT INTO cluster_services (name) VALUES ('coolify');
--
-- PostgreSQL database dump complete
--
EOF

"${VERIFY_SCRIPT}" --service postgres --dir "${PG_DIR}" --verbose

# Sub-test 6a: PostgreSQL dump missing CREATE TABLE (table count assertion failure)
cat <<'EOF' > "${PG_DIR}/dump_notables.sql"
-- PostgreSQL database dump
-- Empty database with no tables
SET statement_timeout = 0;
EOF
set +e
"${VERIFY_SCRIPT}" --file "${PG_DIR}/dump_notables.sql" >/dev/null 2>&1
res_no_tables=$?
set -e
if [[ "${res_no_tables}" -ne 8 ]]; then
  echo "[-] Test 6a Failed: Dump without tables should exit code 8, got ${res_no_tables}" >&2
  exit 1
fi

# Sub-test 6b: Missing header in dump
echo "RANDOM NON-SQL DATA THAT DOES NOT MATCH DUMP FORMAT" > "${PG_DIR}/dump_bad_header.sql"
set +e
"${VERIFY_SCRIPT}" --file "${PG_DIR}/dump_bad_header.sql" >/dev/null 2>&1
res_bad_header=$?
set -e
if [[ "${res_bad_header}" -ne 8 ]]; then
  echo "[-] Test 6b Failed: Bad header should exit code 8, got ${res_bad_header}" >&2
  exit 1
fi

echo "[+] Test 6 Passed: PostgreSQL dump signatures and table assertions verified."

# ==============================================================================
# Test 7: SQLite Physical Corruption Detection
# ==============================================================================
echo ""
echo "[Test 7/8] SQLite Physical Corruption Detection..."
CORRUPT_DIR="${TEST_SANDBOX}/corrupt_db"
mkdir -p "${CORRUPT_DIR}"
sqlite3 "${CORRUPT_DIR}/test.sqlite" <<'EOF'
CREATE TABLE items (id INT PRIMARY KEY, name TEXT);
INSERT INTO items VALUES (1, 'item1'), (2, 'item2'), (3, 'item3');
EOF

# Corrupt the database file by zeroing out the SQLite schema root page (bytes 100-600)
dd if=/dev/zero of="${CORRUPT_DIR}/test.sqlite" bs=1 seek=100 count=500 conv=notrunc >/dev/null 2>&1

set +e
"${VERIFY_SCRIPT}" --file "${CORRUPT_DIR}/test.sqlite" >/dev/null 2>&1
res_corrupt=$?
set -e
if [[ "${res_corrupt}" -ne 2 ]]; then
  echo "[-] Test 7 Failed: Corrupted SQLite DB should exit code 2, got ${res_corrupt}" >&2
  exit 1
fi

echo "[+] Test 7 Passed: Corrupted SQLite page detection confirmed (exit code 2)."

# ==============================================================================
# Test 8: Auto-detection Mode (--service all)
# ==============================================================================
echo ""
echo "[Test 8/8] Auto-detection Mode with Multi-Service Payload..."
MULTI_DIR="${TEST_SANDBOX}/multi_payload"
mkdir -p "${MULTI_DIR}"

# Copy all verified payloads into one root directory
cp -r "${ACTUAL_DIR}/"* "${MULTI_DIR}/"
cp -r "${VW_DIR}/"* "${MULTI_DIR}/"
cp -r "${HA_DIR}/"* "${MULTI_DIR}/"
cp -r "${HA_DIR}/.storage" "${MULTI_DIR}/"
cp -r "${NPM_DIR}/"* "${MULTI_DIR}/"
cp "${PG_DIR}/dump.sql" "${MULTI_DIR}/"

# Re-ensure permissions are 0600 on the copied RSA key
chmod 600 "${MULTI_DIR}/rsa_key.pem"
# Ensure valid sync blob
echo "valid_blob_content" > "${MULTI_DIR}/user-files/sync.blob"
# Ensure valid user
sqlite3 "${MULTI_DIR}/server-files/account.sqlite" "INSERT OR IGNORE INTO users VALUES ('usr_1', 'admin@example.com');"

# Run auto-detection
"${VERIFY_SCRIPT}" --dir "${MULTI_DIR}" --verbose

echo "[+] Test 8 Passed: Auto-detection verified all co-located service backups."

echo ""
echo "================================================================================"
echo "🎉 ALL DATABASE & STORAGE DR INTEGRATION TESTS PASSED SUCCESSFULLY!"
echo "================================================================================"
