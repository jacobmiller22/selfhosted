#!/usr/bin/env bash
# ==============================================================================
# Disaster Recovery (DR): Database & Storage Automated Integrity Suite
# ==============================================================================
# Deep database integrity, foreign key constraint, cryptographic validation,
# and business-critical record count sanity suite for decrypted backup archives.
#
# Supported Services:
#   - actual:         account.sqlite & user-files/*.sqlite integrity + FKs,
#                     users >= 1, transactions >= 0, .blob sync files
#   - vaultwarden:    db.sqlite3 integrity + FKs, users >= 1, ciphers >= 0,
#                     rsa_key.pem (0600 + openssl validate), attachments/ & sends/
#   - homeassistant:  home-assistant_v2.db integrity + FKs, .storage/* JSON syntax
#   - npm:            database.sqlite integrity + FKs, Let's Encrypt certificates
#   - postgres:       SQL dump header signatures, table count assertions (>= 1)
#   - all:            Auto-detects and verifies all services present in directory
#
# Exit Codes:
#   0: Success (all assertions passed)
#   1: Usage error / missing arguments / unsupported service / file not found
#   2: SQLite integrity check failure (PRAGMA integrity_check != ok)
#   3: SQLite foreign key constraint failure (PRAGMA foreign_key_check)
#   4: Business record count sanity assertion failure
#   5: Cryptographic key / certificate / permission check failure
#   6: Storage directory / sync asset failure (.blob, attachments, sends)
#   7: JSON registry or configuration syntax failure
#   8: PostgreSQL dump header or table count assertion failure
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Exit Code Constants
# ------------------------------------------------------------------------------
readonly EXIT_OK=0
readonly EXIT_USAGE_ERR=1
readonly EXIT_INTEGRITY_FAIL=2
readonly EXIT_FK_FAIL=3
readonly EXIT_SANITY_FAIL=4
readonly EXIT_KEY_FAIL=5
readonly EXIT_STORAGE_FAIL=6
readonly EXIT_JSON_FAIL=7
readonly EXIT_PG_FAIL=8

# ------------------------------------------------------------------------------
# Default State
# ------------------------------------------------------------------------------
SERVICE="all"
TARGET_DIR=""
TARGET_FILE=""
VERBOSE=false

# ------------------------------------------------------------------------------
# Logging Helpers
# ------------------------------------------------------------------------------
log_info() {
  echo "[+] $*"
}

log_warn() {
  echo "[!] $*" >&2
}

log_error() {
  echo "[-] ERROR: $*" >&2
}

log_verbose() {
  if [[ "${VERBOSE}" == "true" ]]; then
    echo "    [*] $*"
  fi
}

# ------------------------------------------------------------------------------
# Help & Usage Guide
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Automated Disaster Recovery (DR) integrity and sanity verification suite.
Validates decrypted SQLite databases, foreign keys, record counts, cryptographic
keys, JSON registries, and PostgreSQL dumps.

Options:
  -s, --service <name>   Service to verify (actual, vaultwarden, homeassistant, npm, postgres, all)
                         Default: all (auto-detects services present in target directory)
  -d, --dir <path>       Directory containing decrypted backup payload to inspect
  -f, --file <path>      Direct path to a specific database, dump, or key file
  -v, --verbose          Enable detailed inspection logs and table/record counts
  -h, --help             Display this help message and exit

Exit Codes:
  0  All checks and assertions passed cleanly
  1  Invalid usage, missing parameters, or missing target files
  2  SQLite page/index corruption (PRAGMA integrity_check != 'ok')
  3  SQLite foreign key constraint violation (PRAGMA foreign_key_check)
  4  Business record count sanity failure (users, ciphers, transactions)
  5  Cryptographic key/certificate or permission validation failure
  6  Required storage directory or sync asset missing/empty (.blob, attachments, sends)
  7  JSON registry or configuration file malformed/syntax error
  8  PostgreSQL dump header check or table count assertion failure
EOF
}

# ------------------------------------------------------------------------------
# Parse CLI Arguments
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--service)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        log_error "Missing value for $1"
        exit "${EXIT_USAGE_ERR}"
      fi
      SERVICE="$2"
      shift 2
      ;;
    -d|--dir)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        log_error "Missing value for $1"
        exit "${EXIT_USAGE_ERR}"
      fi
      TARGET_DIR="$2"
      shift 2
      ;;
    -f|--file)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        log_error "Missing value for $1"
        exit "${EXIT_USAGE_ERR}"
      fi
      TARGET_FILE="$2"
      shift 2
      ;;
    -v|--verbose)
      VERBOSE=true
      shift
      ;;
    -h|--help)
      show_help
      exit "${EXIT_OK}"
      ;;
    *)
      log_error "Unknown option: $1"
      show_help >&2
      exit "${EXIT_USAGE_ERR}"
      ;;
  esac
done

# Validate inputs
if [[ -z "${TARGET_DIR}" && -z "${TARGET_FILE}" ]]; then
  log_error "Either --dir <path> or --file <path> must be specified."
  show_help >&2
  exit "${EXIT_USAGE_ERR}"
fi

if [[ -n "${TARGET_DIR}" && ! -d "${TARGET_DIR}" ]]; then
  log_error "Target directory does not exist: ${TARGET_DIR}"
  exit "${EXIT_USAGE_ERR}"
fi

if [[ -n "${TARGET_FILE}" && ! -f "${TARGET_FILE}" ]]; then
  log_error "Target file does not exist: ${TARGET_FILE}"
  exit "${EXIT_USAGE_ERR}"
fi

# ------------------------------------------------------------------------------
# Utility: File Permissions Resolver (Cross-platform Linux & macOS)
# ------------------------------------------------------------------------------
get_file_mode() {
  local file_path="$1"
  local mode=""

  if stat -c "%a" "${file_path}" >/dev/null 2>&1; then
    mode=$(stat -c "%a" "${file_path}" 2>/dev/null)
  elif stat -f "%Lp" "${file_path}" >/dev/null 2>&1; then
    mode=$(stat -f "%Lp" "${file_path}" 2>/dev/null)
  elif command -v python3 >/dev/null 2>&1; then
    mode=$(python3 -c "import os, stat, sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode))[2:])" "${file_path}" 2>/dev/null || echo "")
  fi

  # Normalize by stripping leading zeroes, e.g. 0600 -> 600
  echo "${mode#"${mode%%[!0]*}"}"
}

# ------------------------------------------------------------------------------
# SQLite Core Verification (Integrity & Foreign Keys)
# ------------------------------------------------------------------------------
verify_sqlite_core() {
  local db_path="$1"
  local label="${2:-SQLite database}"

  if [[ ! -f "${db_path}" ]]; then
    log_error "${label} not found at: ${db_path}"
    return "${EXIT_USAGE_ERR}"
  fi

  if [[ ! -s "${db_path}" ]]; then
    log_error "${label} is empty (0 bytes): ${db_path}"
    return "${EXIT_INTEGRITY_FAIL}"
  fi

  log_verbose "Executing PRAGMA integrity_check on ${db_path}"
  local integrity_output
  integrity_output=$(sqlite3 "${db_path}" "PRAGMA integrity_check;" 2>&1) || {
    log_error "Failed to query SQLite database ${db_path}: ${integrity_output}"
    return "${EXIT_INTEGRITY_FAIL}"
  }

  if [[ "${integrity_output}" != "ok" ]]; then
    log_error "SQLite integrity check FAILED on ${db_path}:"
    echo "${integrity_output}" >&2
    return "${EXIT_INTEGRITY_FAIL}"
  fi
  log_verbose "Integrity check passed (ok) for ${db_path}"

  log_verbose "Executing PRAGMA foreign_key_check on ${db_path}"
  local fk_output
  fk_output=$(sqlite3 "${db_path}" "PRAGMA foreign_key_check;" 2>&1) || {
    log_error "Failed to run foreign_key_check on ${db_path}: ${fk_output}"
    return "${EXIT_FK_FAIL}"
  }

  if [[ -n "${fk_output}" ]]; then
    log_error "SQLite foreign key constraint check FAILED on ${db_path}:"
    while IFS= read -r fk_line; do
      echo "    ${fk_line}" >&2
    done <<< "${fk_output}"
    return "${EXIT_FK_FAIL}"
  fi
  log_verbose "Foreign key constraint check passed (clean) for ${db_path}"

  return "${EXIT_OK}"
}

# ------------------------------------------------------------------------------
# Service Verifier: Actual Budget
# ------------------------------------------------------------------------------
verify_actual() {
  local base_dir="$1"
  log_info "Verifying Actual Budget backup integrity at: ${base_dir}"

  # 1. Locate primary account.sqlite
  local account_db=""
  if [[ -f "${base_dir}/server-files/account.sqlite" ]]; then
    account_db="${base_dir}/server-files/account.sqlite"
  elif [[ -f "${base_dir}/account.sqlite" ]]; then
    account_db="${base_dir}/account.sqlite"
  else
    account_db=$(find "${base_dir}" -maxdepth 3 -name "account.sqlite" -type f | head -n 1 || true)
  fi

  if [[ -z "${account_db}" || ! -f "${account_db}" ]]; then
    log_error "Actual Budget account.sqlite not found in ${base_dir}"
    return "${EXIT_USAGE_ERR}"
  fi

  verify_sqlite_core "${account_db}" "Actual Budget account.sqlite"

  # User count assertion: SELECT count(*) FROM users >= 1
  log_verbose "Checking Actual Budget user count in ${account_db}"
  local user_count
  user_count=$(sqlite3 "${account_db}" "SELECT count(*) FROM users;" 2>&1) || {
    log_error "Failed to count users in ${account_db}: ${user_count}"
    return "${EXIT_SANITY_FAIL}"
  }

  if ! [[ "${user_count}" =~ ^[0-9]+$ ]] || [[ "${user_count}" -lt 1 ]]; then
    log_error "Actual Budget user sanity check FAILED on ${account_db}: count=${user_count} (expected >= 1)"
    return "${EXIT_SANITY_FAIL}"
  fi
  log_info "Actual Budget account.sqlite verified cleanly (${user_count} users registered)"

  # 2. Iterate through user budget databases (user-files/*.sqlite)
  local user_dbs=()
  local search_paths=("${base_dir}/user-files" "${base_dir}")
  for sp in "${search_paths[@]}"; do
    if [[ -d "${sp}" ]]; then
      while IFS= read -r -d '' u_db; do
        local bname
        bname="$(basename "${u_db}")"
        if [[ "${bname}" != "account.sqlite" && "${bname}" != "database.sqlite" ]]; then
          user_dbs+=("${u_db}")
        fi
      done < <(find "${sp}" -maxdepth 2 -type f \( -name "*.sqlite" -o -name "*.sqlite3" -o -name "*.db" \) -print0)
    fi
  done

  # Deduplicate user DB array
  local unique_user_dbs=()
  if [[ ${#user_dbs[@]} -gt 0 ]]; then
    while IFS= read -r line; do
      unique_user_dbs+=("${line}")
    done < <(printf '%s\n' "${user_dbs[@]}" | sort -u)
  fi

  log_verbose "Found ${#unique_user_dbs[@]} user budget database(s)"
  for u_db in "${unique_user_dbs[@]}"; do
    verify_sqlite_core "${u_db}" "User budget database $(basename "${u_db}")"

    # Transactions count assertion (>= 0 and table must exist)
    local tx_table_check
    tx_table_check=$(sqlite3 "${u_db}" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='transactions';" 2>&1) || true
    if [[ "${tx_table_check}" == "1" ]]; then
      local tx_count
      tx_count=$(sqlite3 "${u_db}" "SELECT count(*) FROM transactions;" 2>&1) || {
        log_error "Failed to query transactions in ${u_db}: ${tx_count}"
        return "${EXIT_SANITY_FAIL}"
      }
      if ! [[ "${tx_count}" =~ ^[0-9]+$ ]] || [[ "${tx_count}" -lt 0 ]]; then
        log_error "Transactions count sanity check FAILED on ${u_db}: count=${tx_count}"
        return "${EXIT_SANITY_FAIL}"
      fi
      log_verbose "User DB $(basename "${u_db}") transactions count: ${tx_count}"
    else
      log_verbose "User DB $(basename "${u_db}") does not contain 'transactions' table (skipping count check)"
    fi
  done

  # 3. Client-side sync blobs verification (.blob files must exist and size > 0)
  local blob_files=()
  while IFS= read -r -d '' b_file; do
    blob_files+=("${b_file}")
  done < <(find "${base_dir}" -maxdepth 3 -type f -name "*.blob" -print0)

  if [[ ${#blob_files[@]} -eq 0 ]]; then
    log_error "Actual Budget client sync blob check FAILED: No .blob sync files found in ${base_dir}"
    return "${EXIT_STORAGE_FAIL}"
  fi

  for b_file in "${blob_files[@]}"; do
    if [[ ! -s "${b_file}" ]]; then
      log_error "Actual Budget client sync blob is empty (0 bytes): ${b_file}"
      return "${EXIT_STORAGE_FAIL}"
    fi
    log_verbose "Sync blob verified: $(basename "${b_file}") ($(wc -c < "${b_file}" | tr -d ' ') bytes)"
  done
  log_info "Actual Budget sync blobs verified (${#blob_files[@]} intact blob files)"

  log_info "✅ Actual Budget integrity and sanity validation SUCCEEDED"
  return "${EXIT_OK}"
}

# ------------------------------------------------------------------------------
# Service Verifier: Vaultwarden
# ------------------------------------------------------------------------------
verify_vaultwarden() {
  local base_dir="$1"
  log_info "Verifying Vaultwarden backup integrity at: ${base_dir}"

  # 1. Locate db.sqlite3
  local vw_db=""
  if [[ -f "${base_dir}/db.sqlite3" ]]; then
    vw_db="${base_dir}/db.sqlite3"
  elif [[ -f "${base_dir}/data/db.sqlite3" ]]; then
    vw_db="${base_dir}/data/db.sqlite3"
  elif [[ -f "${base_dir}/db.sqlite" ]]; then
    vw_db="${base_dir}/db.sqlite"
  else
    vw_db=$(find "${base_dir}" -maxdepth 3 -name "db.sqlite3" -o -name "db.sqlite" -type f | head -n 1 || true)
  fi

  if [[ -z "${vw_db}" || ! -f "${vw_db}" ]]; then
    log_error "Vaultwarden database (db.sqlite3) not found in ${base_dir}"
    return "${EXIT_USAGE_ERR}"
  fi

  verify_sqlite_core "${vw_db}" "Vaultwarden db.sqlite3"

  # Record counts: users >= 1, ciphers >= 0
  log_verbose "Verifying Vaultwarden user and cipher record counts in ${vw_db}"
  local user_count
  user_count=$(sqlite3 "${vw_db}" "SELECT count(*) FROM users;" 2>&1) || {
    log_error "Failed to count users in Vaultwarden DB ${vw_db}: ${user_count}"
    return "${EXIT_SANITY_FAIL}"
  }
  if ! [[ "${user_count}" =~ ^[0-9]+$ ]] || [[ "${user_count}" -lt 1 ]]; then
    log_error "Vaultwarden users sanity check FAILED on ${vw_db}: count=${user_count} (expected >= 1)"
    return "${EXIT_SANITY_FAIL}"
  fi

  local cipher_count
  cipher_count=$(sqlite3 "${vw_db}" "SELECT count(*) FROM ciphers;" 2>&1) || {
    log_error "Failed to count ciphers in Vaultwarden DB ${vw_db}: ${cipher_count}"
    return "${EXIT_SANITY_FAIL}"
  }
  if ! [[ "${cipher_count}" =~ ^[0-9]+$ ]] || [[ "${cipher_count}" -lt 0 ]]; then
    log_error "Vaultwarden ciphers sanity check FAILED on ${vw_db}: count=${cipher_count} (expected >= 0)"
    return "${EXIT_SANITY_FAIL}"
  fi
  log_info "Vaultwarden database records verified (${user_count} users, ${cipher_count} ciphers)"

  # 2. Cryptographic Keys: rsa_key.pem existence, 0600 permissions, OpenSSL check
  local rsa_key=""
  if [[ -f "${base_dir}/rsa_key.pem" ]]; then
    rsa_key="${base_dir}/rsa_key.pem"
  elif [[ -f "${base_dir}/data/rsa_key.pem" ]]; then
    rsa_key="${base_dir}/data/rsa_key.pem"
  else
    rsa_key=$(find "${base_dir}" -maxdepth 3 -name "rsa_key.pem" -type f | head -n 1 || true)
  fi

  if [[ -z "${rsa_key}" || ! -f "${rsa_key}" ]]; then
    log_error "Vaultwarden rsa_key.pem not found in ${base_dir}"
    return "${EXIT_KEY_FAIL}"
  fi

  # Check permissions (0600 / 600)
  local key_mode
  key_mode=$(get_file_mode "${rsa_key}")
  log_verbose "File permissions for ${rsa_key}: ${key_mode}"
  if [[ "${key_mode}" != "600" && "${key_mode}" != "400" ]]; then
    log_error "Vaultwarden rsa_key.pem permissions check FAILED: mode is ${key_mode} (expected 0600 or 0400)"
    return "${EXIT_KEY_FAIL}"
  fi

  # Validate key with OpenSSL
  local ssl_check
  ssl_check=$(openssl rsa -in "${rsa_key}" -check -noout 2>&1) || {
    log_error "Vaultwarden rsa_key.pem failed OpenSSL cryptographic validation: ${ssl_check}"
    return "${EXIT_KEY_FAIL}"
  }
  log_info "Vaultwarden rsa_key.pem validated cleanly (permissions 0600, OpenSSL check ok)"

  # 3. Storage directories: attachments/ and sends/
  local attachments_dir=""
  local sends_dir=""
  if [[ -d "${base_dir}/attachments" ]]; then
    attachments_dir="${base_dir}/attachments"
  elif [[ -d "${base_dir}/data/attachments" ]]; then
    attachments_dir="${base_dir}/data/attachments"
  fi

  if [[ -d "${base_dir}/sends" ]]; then
    sends_dir="${base_dir}/sends"
  elif [[ -d "${base_dir}/data/sends" ]]; then
    sends_dir="${base_dir}/data/sends"
  fi

  if [[ -z "${attachments_dir}" || ! -d "${attachments_dir}" ]]; then
    log_error "Vaultwarden attachments directory missing in ${base_dir}"
    return "${EXIT_STORAGE_FAIL}"
  fi

  if [[ -z "${sends_dir}" || ! -d "${sends_dir}" ]]; then
    log_error "Vaultwarden sends directory missing in ${base_dir}"
    return "${EXIT_STORAGE_FAIL}"
  fi
  log_info "Vaultwarden attachments and sends storage directories verified intact"

  log_info "✅ Vaultwarden integrity and sanity validation SUCCEEDED"
  return "${EXIT_OK}"
}

# ------------------------------------------------------------------------------
# Service Verifier: Home Assistant
# ------------------------------------------------------------------------------
verify_homeassistant() {
  local base_dir="$1"
  log_info "Verifying Home Assistant backup integrity at: ${base_dir}"

  # 1. Locate home-assistant_v2.db
  local ha_db=""
  if [[ -f "${base_dir}/home-assistant_v2.db" ]]; then
    ha_db="${base_dir}/home-assistant_v2.db"
  elif [[ -f "${base_dir}/config/home-assistant_v2.db" ]]; then
    ha_db="${base_dir}/config/home-assistant_v2.db"
  else
    ha_db=$(find "${base_dir}" -maxdepth 3 -name "home-assistant_v2.db" -type f | head -n 1 || true)
  fi

  if [[ -z "${ha_db}" || ! -f "${ha_db}" ]]; then
    log_error "Home Assistant database (home-assistant_v2.db) not found in ${base_dir}"
    return "${EXIT_USAGE_ERR}"
  fi

  verify_sqlite_core "${ha_db}" "Home Assistant home-assistant_v2.db"
  log_info "Home Assistant database integrity verified cleanly"

  # 2. Inspect .storage/* JSON registries
  local storage_dir=""
  if [[ -d "${base_dir}/.storage" ]]; then
    storage_dir="${base_dir}/.storage"
  elif [[ -d "${base_dir}/config/.storage" ]]; then
    storage_dir="${base_dir}/config/.storage"
  fi

  if [[ -z "${storage_dir}" || ! -d "${storage_dir}" ]]; then
    log_error "Home Assistant .storage directory missing in ${base_dir}"
    return "${EXIT_JSON_FAIL}"
  fi

  local json_files=()
  while IFS= read -r -d '' jf; do
    json_files+=("${jf}")
  done < <(find "${storage_dir}" -maxdepth 1 -type f -print0)

  if [[ ${#json_files[@]} -eq 0 ]]; then
    log_error "Home Assistant .storage directory is empty (expected JSON registries) in ${storage_dir}"
    return "${EXIT_JSON_FAIL}"
  fi

  local verified_json_count=0
  for jf in "${json_files[@]}"; do
    local parse_err=""
    if command -v python3 >/dev/null 2>&1; then
      if ! parse_err=$(python3 -c "import json, sys; json.load(open(sys.argv[1]))" "${jf}" 2>&1); then
        log_error "Home Assistant JSON syntax error in ${jf}:"
        echo "${parse_err}" >&2
        return "${EXIT_JSON_FAIL}"
      fi
    elif command -v jq >/dev/null 2>&1; then
      local jq_out
      if ! jq_out=$(jq . "${jf}" 2>&1 >/dev/null) || [[ "${jq_out}" == *"parse error"* ]]; then
        log_error "Home Assistant JSON syntax error in ${jf}: ${jq_out}"
        return "${EXIT_JSON_FAIL}"
      fi
    else
      log_warn "Neither jq nor python3 available to validate JSON syntax for ${jf}"
    fi
    log_verbose "JSON registry valid: $(basename "${jf}")"
    verified_json_count=$((verified_json_count + 1))
  done

  log_info "Home Assistant storage registries verified (${verified_json_count} JSON files validated)"
  log_info "✅ Home Assistant integrity and sanity validation SUCCEEDED"
  return "${EXIT_OK}"
}

# ------------------------------------------------------------------------------
# Service Verifier: Nginx Proxy Manager (NPM)
# ------------------------------------------------------------------------------
verify_npm() {
  local base_dir="$1"
  log_info "Verifying Nginx Proxy Manager (NPM) backup integrity at: ${base_dir}"

  # 1. Locate database.sqlite
  local npm_db=""
  if [[ -f "${base_dir}/database.sqlite" ]]; then
    npm_db="${base_dir}/database.sqlite"
  elif [[ -f "${base_dir}/data/database.sqlite" ]]; then
    npm_db="${base_dir}/data/database.sqlite"
  else
    npm_db=$(find "${base_dir}" -maxdepth 3 -name "database.sqlite" -type f | head -n 1 || true)
  fi

  if [[ -z "${npm_db}" || ! -f "${npm_db}" ]]; then
    log_error "NPM database (database.sqlite) not found in ${base_dir}"
    return "${EXIT_USAGE_ERR}"
  fi

  verify_sqlite_core "${npm_db}" "NPM database.sqlite"
  log_info "NPM database.sqlite verified cleanly"

  # 2. Inspect Let's Encrypt certificates if present
  local cert_files=()
  while IFS= read -r -d '' cfile; do
    if grep -q "BEGIN CERTIFICATE" "${cfile}" 2>/dev/null; then
      cert_files+=("${cfile}")
    fi
  done < <(find "${base_dir}" -maxdepth 5 -type f \( -name "*.pem" -o -name "*.crt" \) -print0)

  if [[ ${#cert_files[@]} -gt 0 ]]; then
    log_verbose "Found ${#cert_files[@]} SSL certificate(s) to inspect"
    for cfile in "${cert_files[@]}"; do
      local cert_info
      cert_info=$(openssl x509 -enddate -subject -noout -in "${cfile}" 2>&1) || {
        log_error "NPM certificate validation FAILED for ${cfile}: ${cert_info}"
        return "${EXIT_KEY_FAIL}"
      }
      log_verbose "Certificate validated: $(basename "${cfile}") [${cert_info//$'\n'/; }]"
    done
    log_info "NPM Let's Encrypt certificates verified (${#cert_files[@]} valid certificates)"
  else
    log_verbose "No SSL certificates detected in backup (optional for NPM offline snapshot)"
  fi

  log_info "✅ Nginx Proxy Manager integrity and sanity validation SUCCEEDED"
  return "${EXIT_OK}"
}

# ------------------------------------------------------------------------------
# Service Verifier: PostgreSQL Dump
# ------------------------------------------------------------------------------
verify_postgres() {
  local target="$1"
  log_info "Verifying PostgreSQL dump integrity at: ${target}"

  local dump_file=""
  if [[ -f "${target}" ]]; then
    dump_file="${target}"
  else
    # Look for dump.sql or *.sql in target directory
    if [[ -f "${target}/dump.sql" ]]; then
      dump_file="${target}/dump.sql"
    elif [[ -f "${target}/postgres.sql" ]]; then
      dump_file="${target}/postgres.sql"
    else
      dump_file=$(find "${target}" -maxdepth 3 -type f -name "*.sql" | head -n 1 || true)
    fi
  fi

  if [[ -z "${dump_file}" || ! -f "${dump_file}" ]]; then
    log_error "PostgreSQL SQL dump file not found in: ${target}"
    return "${EXIT_USAGE_ERR}"
  fi

  # 1. Non-empty check
  if [[ ! -s "${dump_file}" ]]; then
    log_error "PostgreSQL dump file is empty (0 bytes): ${dump_file}"
    return "${EXIT_PG_FAIL}"
  fi

  # 2. Header and format sanity check
  # Check first 50 lines for PostgreSQL dump signature or standard SQL table declarations
  local header_match=false
  if head -n 50 "${dump_file}" | grep -Ei -q "PostgreSQL database dump|pg_dump|CREATE TABLE|SET statement_timeout"; then
    header_match=true
  fi

  if [[ "${header_match}" != "true" ]]; then
    log_error "PostgreSQL dump header check FAILED on ${dump_file}: missing recognized PostgreSQL signature"
    return "${EXIT_PG_FAIL}"
  fi
  log_verbose "PostgreSQL header signature verified on ${dump_file}"

  # 3. Table count assertion (must define at least 1 table)
  local table_count
  table_count=$(grep -Ei -c '^[[:space:]]*CREATE[[:space:]]+TABLE' "${dump_file}" || true)

  if ! [[ "${table_count}" =~ ^[0-9]+$ ]] || [[ "${table_count}" -lt 1 ]]; then
    log_error "PostgreSQL table count assertion FAILED on ${dump_file}: found ${table_count} tables (expected >= 1)"
    return "${EXIT_PG_FAIL}"
  fi

  log_info "PostgreSQL dump verified cleanly (${table_count} table definitions declared)"
  log_info "✅ PostgreSQL dump integrity validation SUCCEEDED"
  return "${EXIT_OK}"
}

# ------------------------------------------------------------------------------
# Direct File Verification Handler
# ------------------------------------------------------------------------------
verify_single_file() {
  local fpath="$1"
  log_info "Inspecting single file: ${fpath}"

  case "${SERVICE}" in
    postgres)
      verify_postgres "${fpath}"
      ;;
    actual|vaultwarden|homeassistant|npm)
      verify_sqlite_core "${fpath}" "${SERVICE} database file"
      ;;
    all)
      # Guess based on file extension / filename
      local bname
      bname="$(basename "${fpath}")"
      if [[ "${fpath}" == *.sql ]]; then
        verify_postgres "${fpath}"
      elif [[ "${bname}" == "rsa_key.pem" ]]; then
        local key_mode
        key_mode=$(get_file_mode "${fpath}")
        if [[ "${key_mode}" != "600" && "${key_mode}" != "400" ]]; then
          log_error "Key permissions check FAILED: mode is ${key_mode} (expected 0600)"
          return "${EXIT_KEY_FAIL}"
        fi
        openssl rsa -in "${fpath}" -check -noout >/dev/null 2>&1 || {
          log_error "RSA key validation failed on ${fpath}"
          return "${EXIT_KEY_FAIL}"
        }
        log_info "RSA private key verified successfully"
      elif [[ "${fpath}" == *.pem || "${fpath}" == *.crt ]]; then
        openssl x509 -enddate -noout -in "${fpath}" >/dev/null 2>&1 || {
          log_error "X509 certificate validation failed on ${fpath}"
          return "${EXIT_KEY_FAIL}"
        }
        log_info "X509 certificate verified successfully"
      else
        verify_sqlite_core "${fpath}" "Target SQLite database"
      fi
      ;;
    *)
      log_error "Unsupported service for file verification: ${SERVICE}"
      return "${EXIT_USAGE_ERR}"
      ;;
  esac
}

# ------------------------------------------------------------------------------
# Multi-Service Dispatcher / Auto-Detection
# ------------------------------------------------------------------------------
run_verification() {
  if [[ -n "${TARGET_FILE}" ]]; then
    verify_single_file "${TARGET_FILE}"
    return $?
  fi

  case "${SERVICE}" in
    actual)
      verify_actual "${TARGET_DIR}"
      ;;
    vaultwarden)
      verify_vaultwarden "${TARGET_DIR}"
      ;;
    homeassistant)
      verify_homeassistant "${TARGET_DIR}"
      ;;
    npm)
      verify_npm "${TARGET_DIR}"
      ;;
    postgres)
      verify_postgres "${TARGET_DIR}"
      ;;
    all)
      log_info "Auto-detecting and verifying services in: ${TARGET_DIR}"
      local detected=0

      # Check Actual Budget
      if [[ -f "${TARGET_DIR}/server-files/account.sqlite" || -f "${TARGET_DIR}/account.sqlite" ]]; then
        detected=$((detected + 1))
        verify_actual "${TARGET_DIR}"
      fi

      # Check Vaultwarden
      if [[ -f "${TARGET_DIR}/db.sqlite3" || -f "${TARGET_DIR}/data/db.sqlite3" || -f "${TARGET_DIR}/rsa_key.pem" ]]; then
        detected=$((detected + 1))
        verify_vaultwarden "${TARGET_DIR}"
      fi

      # Check Home Assistant
      if [[ -f "${TARGET_DIR}/home-assistant_v2.db" || -f "${TARGET_DIR}/config/home-assistant_v2.db" || -d "${TARGET_DIR}/.storage" ]]; then
        detected=$((detected + 1))
        verify_homeassistant "${TARGET_DIR}"
      fi

      # Check NPM
      if [[ -f "${TARGET_DIR}/database.sqlite" || -f "${TARGET_DIR}/data/database.sqlite" ]]; then
        detected=$((detected + 1))
        verify_npm "${TARGET_DIR}"
      fi

      # Check PostgreSQL
      if [[ -f "${TARGET_DIR}/dump.sql" || -f "${TARGET_DIR}/postgres.sql" ]] || find "${TARGET_DIR}" -maxdepth 2 -type f -name "*.sql" | grep -q .; then
        detected=$((detected + 1))
        verify_postgres "${TARGET_DIR}"
      fi

      if [[ "${detected}" -eq 0 ]]; then
        log_error "No recognized service backup artifacts found in ${TARGET_DIR}"
        log_error "Ensure directory contains expected service files or pass --service <name> explicitly."
        return "${EXIT_USAGE_ERR}"
      fi

      log_info "================================================================================"
      log_info "🎉 All ${detected} detected service backup(s) passed deep integrity verification!"
      log_info "================================================================================"
      return "${EXIT_OK}"
      ;;
    *)
      log_error "Unsupported service: ${SERVICE}"
      show_help >&2
      return "${EXIT_USAGE_ERR}"
      ;;
  esac
}

# Run main verification routine
run_verification
