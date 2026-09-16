#!/usr/bin/env bash
# ==============================================================================
# Backup & Restore Architecture Test Suite
# ==============================================================================
# Validates:
# 1. SQLite online snapshotting
# 2. OpenSSL AES-256-CBC PBKDF2 encryption roundtrip
# 3. Exact cold-storage decryption command from RESTORE.md
# 4. Bit-for-bit checksum and SQLite PRAGMA integrity verification
# ==============================================================================

set -euo pipefail

TEST_DIR=$(mktemp -d /tmp/backup-test-XXXXXX)
trap 'rm -rf "${TEST_DIR}"' EXIT

echo "[*] Setting up test environment in ${TEST_DIR}..."
SRC_DIR="${TEST_DIR}/src"
EXTRACT_DIR="${TEST_DIR}/extracted"
mkdir -p "${SRC_DIR}" "${EXTRACT_DIR}"

# 1. Create a dummy SQLite database with data
TEST_DB="${SRC_DIR}/test_app.sqlite"
sqlite3 "${TEST_DB}" <<EOF
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com');
INSERT INTO users (id, name, email) VALUES (2, 'Bob', 'bob@example.com');
INSERT INTO users (id, name, email) VALUES (3, 'Charlie', 'charlie@example.com');
CREATE TABLE audit_log (timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, action TEXT);
INSERT INTO audit_log (action) VALUES ('INITIAL_INSERT');
EOF

# 2. Create mock secret keys and attachments
echo "-----BEGIN RSA PRIVATE KEY-----" > "${SRC_DIR}/rsa_key.pem"
echo "MOCK_KEY_DATA_FOR_RESTORE_TEST" >> "${SRC_DIR}/rsa_key.pem"
echo "-----END RSA PRIVATE KEY-----" >> "${SRC_DIR}/rsa_key.pem"

mkdir -p "${SRC_DIR}/attachments"
echo "Secret Attachment Payload 12345" > "${SRC_DIR}/attachments/file-1.blob"

# Calculate original SHA256 checksums
ORIG_DB_HASH=$(shasum -a 256 "${TEST_DB}" | awk '{print $1}')
ORIG_KEY_HASH=$(shasum -a 256 "${SRC_DIR}/rsa_key.pem" | awk '{print $1}')
ORIG_ATT_HASH=$(shasum -a 256 "${SRC_DIR}/attachments/file-1.blob" | awk '{print $1}')

echo "[+] Original DB SHA256:         ${ORIG_DB_HASH}"
echo "[+] Original RSA Key SHA256:    ${ORIG_KEY_HASH}"
echo "[+] Original Attachment SHA256: ${ORIG_ATT_HASH}"

# 3. Run SQLite Online Snapshot into staging
STAGING_DIR="${TEST_DIR}/staging"
mkdir -p "${STAGING_DIR}"
sqlite3 "${TEST_DB}" ".backup '${STAGING_DIR}/test_app.sqlite'"
cp "${SRC_DIR}/rsa_key.pem" "${STAGING_DIR}/rsa_key.pem"
cp -r "${SRC_DIR}/attachments" "${STAGING_DIR}/attachments"

# 4. OpenSSL AES-256-CBC Encryption
TEST_PASSPHRASE="CorrectHorseBatteryStaple-OfflineWallet2026"
ARCHIVE_ENC="${TEST_DIR}/test-service-backup-2026-09-16.tar.gz.enc"

echo "[*] Encrypting with OpenSSL AES-256-CBC (PBKDF2 100k iters)..."
export BACKUP_PASSPHRASE="${TEST_PASSPHRASE}"
tar -cz -C "${STAGING_DIR}" . | \
  openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
  -pass env:BACKUP_PASSPHRASE \
  -out "${ARCHIVE_ENC}"

ARCHIVE_SIZE=$(wc -c < "${ARCHIVE_ENC}" | tr -d ' ')
echo "[+] Encrypted Archive Created: ${ARCHIVE_SIZE} bytes"

# Verify file starts with OpenSSL magic salt header "Salted__"
HEADER_CHECK=$(head -c 8 "${ARCHIVE_ENC}")
if [[ "${HEADER_CHECK}" != "Salted__" ]]; then
  echo "[-] ERROR: Archive header is not standard OpenSSL Salted__!" >&2
  exit 1
fi
echo "[+] Verified OpenSSL Salted__ header present."

# 5. Restore: Decrypt with exact RESTORE.md command
echo "[*] Decrypting archive using RESTORE.md procedure..."
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${ARCHIVE_ENC}" \
  -pass env:BACKUP_PASSPHRASE | \
  tar -xz -C "${EXTRACT_DIR}"

# 6. Integrity Verification
echo "[*] Verifying integrity of extracted data..."

# Check SQLite PRAGMA integrity
INTEGRITY_RESULT=$(sqlite3 "${EXTRACT_DIR}/test_app.sqlite" "PRAGMA integrity_check;")
if [[ "${INTEGRITY_RESULT}" != "ok" ]]; then
  echo "[-] ERROR: SQLite integrity check failed: ${INTEGRITY_RESULT}" >&2
  exit 1
fi
echo "[+] SQLite integrity check: OK"

# Check row counts
ROW_COUNT=$(sqlite3 "${EXTRACT_DIR}/test_app.sqlite" "SELECT COUNT(*) FROM users;")
if [[ "${ROW_COUNT}" -ne 3 ]]; then
  echo "[-] ERROR: User row count mismatch! Expected 3, got ${ROW_COUNT}" >&2
  exit 1
fi
echo "[+] SQLite row count verified: ${ROW_COUNT} rows."

# Verify checksums of non-database files
EXTRACT_KEY_HASH=$(shasum -a 256 "${EXTRACT_DIR}/rsa_key.pem" | awk '{print $1}')
EXTRACT_ATT_HASH=$(shasum -a 256 "${EXTRACT_DIR}/attachments/file-1.blob" | awk '{print $1}')

if [[ "${EXTRACT_KEY_HASH}" != "${ORIG_KEY_HASH}" ]]; then
  echo "[-] ERROR: RSA key SHA256 mismatch!" >&2
  exit 1
fi
if [[ "${EXTRACT_ATT_HASH}" != "${ORIG_ATT_HASH}" ]]; then
  echo "[-] ERROR: Attachment SHA256 mismatch!" >&2
  exit 1
fi

echo "[+] RSA Key SHA256 matches bit-for-bit."
echo "[+] Attachment SHA256 matches bit-for-bit."
echo ""
echo "================================================================================"
echo "🎉 ALL BACKUP & RESTORE VERIFICATION TESTS PASSED CLEANLY!"
echo "================================================================================"
