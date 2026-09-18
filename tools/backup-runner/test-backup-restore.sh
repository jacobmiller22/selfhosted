#!/usr/bin/env bash
# ==============================================================================
# Comprehensive Backup & Restore Architecture Test Suite
# ==============================================================================
# Validates:
# 1. Generic SQLite online snapshotting & OpenSSL AES-256-CBC PBKDF2 roundtrip
# 2. Actual Budget real multi-DB & sync-blob topology backup and restore
# 3. Vaultwarden live WAL DB, RSA keypair, attachments, sends, & config restore
# 4. Strict compatibility with RESTORE.md cold-storage procedure
# 5. Bit-for-bit checksums and PRAGMA integrity_check
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d /tmp/backup-suite-XXXXXX)
trap 'rm -rf "${TEST_DIR}"' EXIT

echo "================================================================================"
echo "🧪 Running Backup & Restore Test Suite in ${TEST_DIR}"
echo "================================================================================"

# ==============================================================================
# Test 1: Generic OpenSSL AES-256-CBC PBKDF2 Roundtrip
# ==============================================================================
echo ""
echo "[Test 1/3] Testing Generic OpenSSL AES-256-CBC PBKDF2 Roundtrip..."
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
  openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
  -pass env:BACKUP_PASSPHRASE \
  -out "${T1_ARCHIVE}"

# Verify Salted__ header
if [[ "$(head -c 8 "${T1_ARCHIVE}")" != "Salted__" ]]; then
  echo "[-] Test 1 Failed: Archive missing OpenSSL Salted__ header" >&2
  exit 1
fi

# Decrypt
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
# Test 2: Actual Budget Topology Backup & Restoration
# ==============================================================================
echo ""
echo "[Test 2/3] Testing Actual Budget Topology Backup & Restoration..."
ACTUAL_DATA="${TEST_DIR}/actual-data"
ACTUAL_EXTRACT="${TEST_DIR}/actual-extract"
mkdir -p "${ACTUAL_DATA}/server-files" "${ACTUAL_DATA}/user-files" "${ACTUAL_EXTRACT}"

# Create server-files/account.sqlite
sqlite3 "${ACTUAL_DATA}/server-files/account.sqlite" <<EOF
CREATE TABLE users (id TEXT PRIMARY KEY, user_name TEXT);
INSERT INTO users VALUES ('u1', 'testuser@example.com');
EOF

# Create multiple user-files/group-*.sqlite
sqlite3 "${ACTUAL_DATA}/user-files/group-1111-2222.sqlite" <<EOF
CREATE TABLE transactions (id TEXT PRIMARY KEY, amount INTEGER, payee TEXT);
INSERT INTO transactions VALUES ('t1', 1250, 'Groceries');
INSERT INTO transactions VALUES ('t2', 4500, 'Utilities');
EOF

sqlite3 "${ACTUAL_DATA}/user-files/group-3333-4444.sqlite" <<EOF
CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT);
INSERT INTO accounts VALUES ('a1', 'Checking');
EOF

# Simulate active WAL file for one of the user files
sqlite3 "${ACTUAL_DATA}/user-files/group-1111-2222.sqlite" "PRAGMA journal_mode=WAL;"
touch "${ACTUAL_DATA}/user-files/group-1111-2222.sqlite-wal"
touch "${ACTUAL_DATA}/user-files/group-1111-2222.sqlite-shm"

# Create user blobs and .migrate
echo "encrypted-sync-blob-1111" > "${ACTUAL_DATA}/user-files/file-1111.blob"
echo "encrypted-sync-blob-2222" > "${ACTUAL_DATA}/user-files/file-2222.blob"
echo '{"version": 17}' > "${ACTUAL_DATA}/.migrate"

ORIG_BLOB1_HASH=$(shasum -a 256 "${ACTUAL_DATA}/user-files/file-1111.blob" | awk '{print $1}')
ORIG_BLOB2_HASH=$(shasum -a 256 "${ACTUAL_DATA}/user-files/file-2222.blob" | awk '{print $1}')
ORIG_MIGRATE_HASH=$(shasum -a 256 "${ACTUAL_DATA}/.migrate" | awk '{print $1}')

# Run Actual backup runner script
ACTUAL_OUTPUT="${TEST_DIR}/actual-output"
SERVICE_NAME="actual" \
BACKUP_SOURCE_DIR="${ACTUAL_DATA}" \
BACKUP_PASSPHRASE="FireproofWalletSecret2026" \
BACKUP_DEST_BUCKET="" \
BACKUP_DEST_ACCESS_KEY_ID="" \
HEALTHCHECK_PING_URL="" \
DISCORD_WEBHOOK_URL="" \
OUTPUT_DIR="${ACTUAL_OUTPUT}" \
"${ROOT_DIR}/actual/backup/backup.sh"

ACTUAL_ARCHIVE=$(find "${ACTUAL_OUTPUT}" -name "actual-backup-*.tar.gz.enc" | head -n 1)
if [[ -z "${ACTUAL_ARCHIVE}" || ! -f "${ACTUAL_ARCHIVE}" ]]; then
  echo "[-] Test 2 Failed: actual backup archive not created." >&2
  exit 1
fi
echo "[+] Actual backup archive generated: $(basename "${ACTUAL_ARCHIVE}")"

# Decrypt using RESTORE.md procedure
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${ACTUAL_ARCHIVE}" \
  -pass pass:FireproofWalletSecret2026 | \
  tar -xz -C "${ACTUAL_EXTRACT}"

# Ensure no transient WAL / SHM files were packaged in backup
if find "${ACTUAL_EXTRACT}" -name "*-wal" -o -name "*-shm" | grep -q .; then
  echo "[-] Test 2 Failed: Unwanted WAL/SHM journal files found in backup archive." >&2
  exit 1
fi

# Verify integrity of all SQLite databases
[[ "$(sqlite3 "${ACTUAL_EXTRACT}/server-files/account.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${ACTUAL_EXTRACT}/server-files/account.sqlite" "SELECT COUNT(*) FROM users;")" -eq 1 ]]

[[ "$(sqlite3 "${ACTUAL_EXTRACT}/user-files/group-1111-2222.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${ACTUAL_EXTRACT}/user-files/group-1111-2222.sqlite" "SELECT COUNT(*) FROM transactions;")" -eq 2 ]]

[[ "$(sqlite3 "${ACTUAL_EXTRACT}/user-files/group-3333-4444.sqlite" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${ACTUAL_EXTRACT}/user-files/group-3333-4444.sqlite" "SELECT COUNT(*) FROM accounts;")" -eq 1 ]]

# Verify blobs and metadata bit-for-bit
RESTORE_BLOB1_HASH=$(shasum -a 256 "${ACTUAL_EXTRACT}/user-files/file-1111.blob" | awk '{print $1}')
RESTORE_BLOB2_HASH=$(shasum -a 256 "${ACTUAL_EXTRACT}/user-files/file-2222.blob" | awk '{print $1}')
RESTORE_MIGRATE_HASH=$(shasum -a 256 "${ACTUAL_EXTRACT}/.migrate" | awk '{print $1}')

[[ "${RESTORE_BLOB1_HASH}" == "${ORIG_BLOB1_HASH}" ]]
[[ "${RESTORE_BLOB2_HASH}" == "${ORIG_BLOB2_HASH}" ]]
[[ "${RESTORE_MIGRATE_HASH}" == "${ORIG_MIGRATE_HASH}" ]]
echo "[+] Test 2 Passed: Actual Budget backup & restore validated cleanly."

# ==============================================================================
# Test 3: Vaultwarden Full Application State Backup & Restoration
# ==============================================================================
echo ""
echo "[Test 3/3] Testing Vaultwarden Full Application State Backup & Restoration..."
VW_DATA="${TEST_DIR}/vw-data"
VW_EXTRACT="${TEST_DIR}/vw-extract"
mkdir -p "${VW_DATA}/attachments" "${VW_DATA}/sends" "${VW_EXTRACT}"

# Create Vaultwarden db.sqlite3 with WAL mode and active journals
sqlite3 "${VW_DATA}/db.sqlite3" <<EOF
PRAGMA journal_mode=WAL;
CREATE TABLE ciphers (uuid TEXT PRIMARY KEY, name TEXT, notes TEXT);
INSERT INTO ciphers VALUES ('c1', 'GitHub Token', 'ghp_secret123');
INSERT INTO ciphers VALUES ('c2', 'Banking Password', 'CorrectHorseStaple');
EOF
touch "${VW_DATA}/db.sqlite3-wal"
touch "${VW_DATA}/db.sqlite3-shm"

# Create RSA keys, attachments, sends, config.json
echo "-----BEGIN RSA PRIVATE KEY-----" > "${VW_DATA}/rsa_key.pem"
echo "MIIEowIBAAKCAQEA0vVaultwardenKeyData..." >> "${VW_DATA}/rsa_key.pem"
echo "-----END RSA PRIVATE KEY-----" >> "${VW_DATA}/rsa_key.pem"

echo "-----BEGIN PUBLIC KEY-----" > "${VW_DATA}/rsa_key.pub"
echo "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A..." >> "${VW_DATA}/rsa_key.pub"
echo "-----END PUBLIC KEY-----" >> "${VW_DATA}/rsa_key.pub"

echo "encrypted-attachment-binary-payload" > "${VW_DATA}/attachments/user_att_1.bin"
echo '{"id": "send1", "name": "Document Send"}' > "${VW_DATA}/sends/send_meta_1.json"
echo '{"domain": "https://vw.cloud.jacobmiller22.com", "signups_allowed": false}' > "${VW_DATA}/config.json"

ORIG_KEY_PEM_HASH=$(shasum -a 256 "${VW_DATA}/rsa_key.pem" | awk '{print $1}')
ORIG_KEY_PUB_HASH=$(shasum -a 256 "${VW_DATA}/rsa_key.pub" | awk '{print $1}')
ORIG_ATT_HASH=$(shasum -a 256 "${VW_DATA}/attachments/user_att_1.bin" | awk '{print $1}')
ORIG_SEND_HASH=$(shasum -a 256 "${VW_DATA}/sends/send_meta_1.json" | awk '{print $1}')
ORIG_CFG_HASH=$(shasum -a 256 "${VW_DATA}/config.json" | awk '{print $1}')

# Run Vaultwarden backup runner script
VW_OUTPUT="${TEST_DIR}/vw-output"
unset BACKUP_PASSPHRASE
SERVICE_NAME="vaultwarden" \
BACKUP_SOURCE_DIR="${VW_DATA}" \
BACKUP_ENCRYPTION_KEY="VaultPassphraseFromWallet" \
BACKUP_DEST_BUCKET="" \
BACKUP_DEST_ACCESS_KEY_ID="" \
HEALTHCHECK_PING_URL="" \
DISCORD_WEBHOOK_URL="" \
OUTPUT_DIR="${VW_OUTPUT}" \
"${ROOT_DIR}/vaultwarden/backup/backup.sh"

VW_ARCHIVE=$(find "${VW_OUTPUT}" -name "vaultwarden-backup-*.tar.gz.enc" | head -n 1)
if [[ -z "${VW_ARCHIVE}" || ! -f "${VW_ARCHIVE}" ]]; then
  echo "[-] Test 3 Failed: vaultwarden backup archive not created." >&2
  exit 1
fi
echo "[+] Vaultwarden backup archive generated: $(basename "${VW_ARCHIVE}")"

# Decrypt using RESTORE.md procedure
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in "${VW_ARCHIVE}" \
  -pass pass:VaultPassphraseFromWallet | \
  tar -xz -C "${VW_EXTRACT}"

# Ensure no transient WAL / SHM files leaked into backup
if find "${VW_EXTRACT}" -name "*-wal" -o -name "*-shm" | grep -q .; then
  echo "[-] Test 3 Failed: Unwanted WAL/SHM journal files found in Vaultwarden backup archive." >&2
  exit 1
fi

# Verify SQLite integrity
[[ "$(sqlite3 "${VW_EXTRACT}/db.sqlite3" "PRAGMA integrity_check;")" == "ok" ]]
[[ "$(sqlite3 "${VW_EXTRACT}/db.sqlite3" "SELECT COUNT(*) FROM ciphers;")" -eq 2 ]]

# Verify all assets match bit-for-bit
RESTORE_KEY_PEM_HASH=$(shasum -a 256 "${VW_EXTRACT}/rsa_key.pem" | awk '{print $1}')
RESTORE_KEY_PUB_HASH=$(shasum -a 256 "${VW_EXTRACT}/rsa_key.pub" | awk '{print $1}')
RESTORE_ATT_HASH=$(shasum -a 256 "${VW_EXTRACT}/attachments/user_att_1.bin" | awk '{print $1}')
RESTORE_SEND_HASH=$(shasum -a 256 "${VW_EXTRACT}/sends/send_meta_1.json" | awk '{print $1}')
RESTORE_CFG_HASH=$(shasum -a 256 "${VW_EXTRACT}/config.json" | awk '{print $1}')

[[ "${RESTORE_KEY_PEM_HASH}" == "${ORIG_KEY_PEM_HASH}" ]]
[[ "${RESTORE_KEY_PUB_HASH}" == "${ORIG_KEY_PUB_HASH}" ]]
[[ "${RESTORE_ATT_HASH}" == "${ORIG_ATT_HASH}" ]]
[[ "${RESTORE_SEND_HASH}" == "${ORIG_SEND_HASH}" ]]
[[ "${RESTORE_CFG_HASH}" == "${ORIG_CFG_HASH}" ]]
echo "[+] Test 3 Passed: Vaultwarden full state backup & restore validated cleanly."

echo ""
echo "================================================================================"
echo "🎉 ALL BACKUP & RESTORE ARCHITECTURE TESTS PASSED SUCCESSFULLY!"
echo "================================================================================"
