#!/usr/bin/env bash
# ==============================================================================
# Ephemeral Staging: Live Production Snapshot Hydration Engine
# ==============================================================================
# Performs zero-downtime, zero-blast-radius snapshotting of live production
# databases and companion application state into isolated staging volumes.
#
# Supported Services:
# - Actual Budget (actual):
#     Atomic snapshot of account.sqlite (or server-files/account.sqlite),
#     atomic snapshots of user-files/*.sqlite, copies user-files/*.blob,
#     copies .migrate/config.json, enforces 1000:1000 ownership.
# - Vaultwarden (vaultwarden):
#     Atomic snapshot of db.sqlite3, copies rsa_key.pem (chmod 600),
#     rsa_key.pub, attachments/, sends/, config.json.
#
# Safety Guarantees:
# - Strict shell safety (set -euo pipefail)
# - Online SQLite snapshots via sqlite3 .backup (never raw cp on active DBs)
# - Post-hydration PRAGMA integrity_check validation
# - Production/staging directory collision prevention
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Default Settings & Variables
# ------------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SERVICE=""
ACTION="hydrate"
DO_START=false
DRY_RUN=false
PROD_DATA_DIR="${PROD_DATA_DIR:-}"
STAGE_DATA_DIR="${STAGE_DATA_DIR:-}"
DOCKER_BIN="${DOCKER_CMD:-docker}"

# ------------------------------------------------------------------------------
# Help & Usage Display
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [SERVICE] [OPTIONS]
       $(basename "$0") --reset <service> [OPTIONS]
       $(basename "$0") --stop <service> [OPTIONS]

Hydrates ephemeral staging environments with consistent online snapshots of production databases.

Services:
  actual                     Actual Budget (snapshot account.sqlite, user-files/*.sqlite, blobs)
  vaultwarden                Vaultwarden (snapshot db.sqlite3, copy rsa keys, attachments, sends)

Options & Actions:
  --start                    Start the staging container after successful hydration
  --stop <service>           Stop the staging container without hydrating
  --reset <service>          Wipe staging volume/directory and re-hydrate fresh snapshot
  --dry-run                  Simulate actions without modifying files or container states
  --prod-data-dir <path>     Explicit path to production data directory (or set PROD_DATA_DIR)
  --stage-data-dir <path>    Explicit path to staging data directory (or set STAGE_DATA_DIR)
  -s, --service <service>    Service name ('actual' or 'vaultwarden')
  -h, --help                 Display this help message and exit

Environment Variables:
  PROD_DATA_DIR              Path to production data volume / directory
  STAGE_DATA_DIR             Path to staging data volume / directory
  DOCKER_CMD                 Docker command binary (default: 'docker')
  CHOWN_CMD                  Custom chown command to override default chown -R 1000:1000
EOF
}

# ------------------------------------------------------------------------------
# Parse CLI Arguments
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    actual|vaultwarden)
      SERVICE="$1"
      shift
      ;;
    -s|--service)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      SERVICE="$2"
      shift 2
      ;;
    --service=*)
      SERVICE="${1#*=}"
      shift
      ;;
    --reset)
      ACTION="reset"
      if [[ -n "${2:-}" && "${2}" != -* ]]; then
        SERVICE="$2"
        shift 2
      else
        shift 1
      fi
      ;;
    --reset=*)
      ACTION="reset"
      SERVICE="${1#*=}"
      shift
      ;;
    --stop)
      ACTION="stop"
      if [[ -n "${2:-}" && "${2}" != -* ]]; then
        SERVICE="$2"
        shift 2
      else
        shift 1
      fi
      ;;
    --stop=*)
      ACTION="stop"
      SERVICE="${1#*=}"
      shift
      ;;
    --start)
      DO_START=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --prod-data-dir)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      PROD_DATA_DIR="$2"
      shift 2
      ;;
    --prod-data-dir=*)
      PROD_DATA_DIR="${1#*=}"
      shift
      ;;
    --stage-data-dir)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      STAGE_DATA_DIR="$2"
      shift 2
      ;;
    --stage-data-dir=*)
      STAGE_DATA_DIR="${1#*=}"
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "[-] ERROR: Unknown option: $1" >&2
      echo "Run '$(basename "$0") --help' for usage." >&2
      exit 1
      ;;
  esac
done

# ------------------------------------------------------------------------------
# Validate Service
# ------------------------------------------------------------------------------
if [[ -z "${SERVICE}" ]]; then
  echo "[-] ERROR: Service name is required ('actual' or 'vaultwarden')." >&2
  echo "Run '$(basename "$0") --help' for usage." >&2
  exit 1
fi

if [[ "${SERVICE}" != "actual" && "${SERVICE}" != "vaultwarden" ]]; then
  echo "[-] ERROR: Unsupported service '${SERVICE}'. Supported services: actual, vaultwarden." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Service Metadata Resolution
# ------------------------------------------------------------------------------
case "${SERVICE}" in
  actual)
    CONTAINER_NAME="actual-server-staging"
    COMPOSE_FILE="${REPO_ROOT}/actual/compose.yml"
    PROD_VOL_NAME="actual-data"
    STAGE_VOL_NAME="actual-stage-data"
    ;;
  vaultwarden)
    CONTAINER_NAME="vaultwarden-staging"
    COMPOSE_FILE="${REPO_ROOT}/vaultwarden/compose.yml"
    PROD_VOL_NAME="vw-data"
    STAGE_VOL_NAME="vw-stage-data"
    ;;
esac

# ------------------------------------------------------------------------------
# Stop Action Handler
# ------------------------------------------------------------------------------
if [[ "${ACTION}" == "stop" ]]; then
  echo "[+] Stopping staging container '${CONTAINER_NAME}'..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] would run: ${DOCKER_BIN} compose -f ${COMPOSE_FILE} --profile staging stop ${CONTAINER_NAME}"
  else
    if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
      echo "[-] ERROR: Docker executable '${DOCKER_BIN}' not found in PATH." >&2
      exit 1
    fi
    "${DOCKER_BIN}" compose -f "${COMPOSE_FILE}" --profile staging stop "${CONTAINER_NAME}"
    echo "[+] Staging container '${CONTAINER_NAME}' stopped successfully."
  fi
  exit 0
fi

# ------------------------------------------------------------------------------
# Volume & Directory Path Resolution
# ------------------------------------------------------------------------------
resolve_volume_path() {
  local vol_name="$1"
  local path=""

  if command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
    path=$("${DOCKER_BIN}" volume inspect "${vol_name}" --format '{{.Mountpoint}}' 2>/dev/null || true)
    if [[ -z "${path}" ]]; then
      local matching_vol
      matching_vol=$("${DOCKER_BIN}" volume ls -q --filter "name=${vol_name}" 2>/dev/null | head -n 1 || true)
      if [[ -n "${matching_vol}" ]]; then
        path=$("${DOCKER_BIN}" volume inspect "${matching_vol}" --format '{{.Mountpoint}}' 2>/dev/null || true)
      fi
    fi
  fi

  if [[ -z "${path}" && -d "/var/lib/docker/volumes/${vol_name}/_data" ]]; then
    path="/var/lib/docker/volumes/${vol_name}/_data"
  fi

  echo "${path}"
}

if [[ -z "${PROD_DATA_DIR}" ]]; then
  PROD_DATA_DIR="$(resolve_volume_path "${PROD_VOL_NAME}")"
fi

if [[ -z "${PROD_DATA_DIR}" ]]; then
  if [[ "${DRY_RUN}" == "true" ]]; then
    PROD_DATA_DIR="/var/lib/docker/volumes/${PROD_VOL_NAME}/_data"
    echo "[dry-run] PROD_DATA_DIR unresolved; simulated path: ${PROD_DATA_DIR}"
  else
    echo "[-] ERROR: Production data directory could not be resolved for '${SERVICE}'." >&2
    echo "Specify --prod-data-dir <path> or set PROD_DATA_DIR environment variable." >&2
    exit 1
  fi
fi

if [[ "${DRY_RUN}" != "true" && ! -d "${PROD_DATA_DIR}" ]]; then
  echo "[-] ERROR: Production data directory '${PROD_DATA_DIR}' does not exist." >&2
  exit 1
fi

if [[ -z "${STAGE_DATA_DIR}" ]]; then
  STAGE_DATA_DIR="$(resolve_volume_path "${STAGE_VOL_NAME}")"
fi

if [[ -z "${STAGE_DATA_DIR}" ]]; then
  if [[ "${DRY_RUN}" == "true" ]]; then
    STAGE_DATA_DIR="/var/lib/docker/volumes/${STAGE_VOL_NAME}/_data"
    echo "[dry-run] STAGE_DATA_DIR unresolved; simulated path: ${STAGE_DATA_DIR}"
  else
    echo "[-] ERROR: Staging data directory could not be resolved for '${SERVICE}'." >&2
    echo "Specify --stage-data-dir <path> or set STAGE_DATA_DIR environment variable." >&2
    exit 1
  fi
fi

# ------------------------------------------------------------------------------
# Blast Radius Safety Checks
# ------------------------------------------------------------------------------
if [[ "${STAGE_DATA_DIR}" == "${PROD_DATA_DIR}" ]]; then
  echo "[-] FATAL BLAST-RADIUS VIOLATION: STAGE_DATA_DIR is identical to PROD_DATA_DIR (${PROD_DATA_DIR})!" >&2
  exit 1
fi

if [[ -z "${STAGE_DATA_DIR}" || "${STAGE_DATA_DIR}" == "/" || "${STAGE_DATA_DIR}" == "/root" || "${STAGE_DATA_DIR}" == "/home" ]]; then
  echo "[-] FATAL: Refusing to operate on unsafe STAGE_DATA_DIR '${STAGE_DATA_DIR}'." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Reset Staging Volume Handler
# ------------------------------------------------------------------------------
if [[ "${ACTION}" == "reset" ]]; then
  echo "[+] Initiating staging reset for '${SERVICE}'..."

  # Stop staging container if docker is available and compose file exists
  if command -v "${DOCKER_BIN}" >/dev/null 2>&1 && [[ -f "${COMPOSE_FILE}" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would run: ${DOCKER_BIN} compose -f ${COMPOSE_FILE} --profile staging stop ${CONTAINER_NAME}"
    else
      "${DOCKER_BIN}" compose -f "${COMPOSE_FILE}" --profile staging stop "${CONTAINER_NAME}" 2>/dev/null || true
    fi
  fi

  echo "[+] Wiping staging directory: ${STAGE_DATA_DIR}..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] would delete all files and subdirectories inside ${STAGE_DATA_DIR}"
  else
    if [[ -d "${STAGE_DATA_DIR}" ]]; then
      find "${STAGE_DATA_DIR}" -mindepth 1 -delete
      echo "[+] Staging directory wiped clean."
    fi
  fi
fi

# Ensure staging directory exists
if [[ "${DRY_RUN}" != "true" ]]; then
  mkdir -p "${STAGE_DATA_DIR}"
fi

# ------------------------------------------------------------------------------
# SQLite Integrity Validation Function
# ------------------------------------------------------------------------------
validate_integrity() {
  local target_dir="$1"
  echo "[+] Running PRAGMA integrity_check on hydrated SQLite databases in ${target_dir}..."

  local dbs=()
  while IFS= read -r -d '' db_path; do
    dbs+=("${db_path}")
  done < <(find "${target_dir}" -type f \( -name "*.sqlite" -o -name "*.sqlite3" -o -name "*.db" \) -print0)

  if [[ ${#dbs[@]} -eq 0 ]]; then
    echo "[-] ERROR: No SQLite databases found in ${target_dir} for integrity validation!" >&2
    return 1
  fi

  for db in "${dbs[@]}"; do
    local rel="${db#"${target_dir}/"}"
    echo "[+] Validating SQLite database: ${rel}..."
    local check_res
    if ! check_res=$(sqlite3 "${db}" "PRAGMA integrity_check;" 2>&1); then
      echo "[-] ERROR: SQLite command failed for ${rel}: ${check_res}" >&2
      return 1
    fi
    if [[ "${check_res}" != "ok" ]]; then
      echo "[-] ERROR: Integrity check failed for ${rel}: ${check_res}" >&2
      return 1
    fi
  done

  echo "[+] Integrity validation passed: ${#dbs[@]} SQLite database(s) verified consistent."
  return 0
}

# ------------------------------------------------------------------------------
# Service Hydration Logic
# ------------------------------------------------------------------------------
echo "[+] Starting snapshot hydration from ${PROD_DATA_DIR} to ${STAGE_DATA_DIR}..."

if [[ "${SERVICE}" == "actual" ]]; then
  # 1. Snapshot account.sqlite (check server-files/account.sqlite or account.sqlite)
  found_account=false
  if [[ -f "${PROD_DATA_DIR}/server-files/account.sqlite" ]]; then
    found_account=true
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would snapshot ${PROD_DATA_DIR}/server-files/account.sqlite to ${STAGE_DATA_DIR}/server-files/account.sqlite"
    else
      mkdir -p "${STAGE_DATA_DIR}/server-files"
      dest_db="${STAGE_DATA_DIR}/server-files/account.sqlite"
      rm -f "${dest_db}-wal" "${dest_db}-shm"
      escaped_dest="${dest_db//\'/\'\'}"
      echo "[+] Snapshotting SQLite DB: server-files/account.sqlite..."
      if ! sqlite3 "${PROD_DATA_DIR}/server-files/account.sqlite" ".backup '${escaped_dest}'"; then
        echo "[-] ERROR: SQLite .backup failed for server-files/account.sqlite" >&2
        exit 1
      fi
    fi
  fi

  if [[ -f "${PROD_DATA_DIR}/account.sqlite" ]]; then
    found_account=true
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would snapshot ${PROD_DATA_DIR}/account.sqlite to ${STAGE_DATA_DIR}/account.sqlite"
    else
      dest_db="${STAGE_DATA_DIR}/account.sqlite"
      rm -f "${dest_db}-wal" "${dest_db}-shm"
      escaped_dest="${dest_db//\'/\'\'}"
      echo "[+] Snapshotting SQLite DB: account.sqlite..."
      if ! sqlite3 "${PROD_DATA_DIR}/account.sqlite" ".backup '${escaped_dest}'"; then
        echo "[-] ERROR: SQLite .backup failed for account.sqlite" >&2
        exit 1
      fi
    fi
  fi

  if [[ "${found_account}" == "false" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] warning: account.sqlite not found in prod directory"
    else
      echo "[-] ERROR: account.sqlite not found in ${PROD_DATA_DIR} (checked server-files/account.sqlite and account.sqlite)" >&2
      exit 1
    fi
  fi

  # 2. Snapshot user-files/*.sqlite and copy user-files/*.blob
  if [[ -d "${PROD_DATA_DIR}/user-files" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would snapshot SQLite DBs and copy .blob sync files from ${PROD_DATA_DIR}/user-files"
    else
      mkdir -p "${STAGE_DATA_DIR}/user-files"

      # Snapshot all SQLite databases found under user-files
      while IFS= read -r -d '' db_file; do
        rel_path="${db_file#"${PROD_DATA_DIR}/user-files/"}"
        dest_db="${STAGE_DATA_DIR}/user-files/${rel_path}"
        mkdir -p "$(dirname "${dest_db}")"
        rm -f "${dest_db}-wal" "${dest_db}-shm"
        escaped_dest="${dest_db//\'/\'\'}"
        echo "[+] Snapshotting SQLite DB: user-files/${rel_path}..."
        if ! sqlite3 "${db_file}" ".backup '${escaped_dest}'"; then
          echo "[-] ERROR: SQLite .backup failed for user-files/${rel_path}" >&2
          exit 1
        fi
      done < <(find "${PROD_DATA_DIR}/user-files" -type f \( -name "*.sqlite" -o -name "*.sqlite3" -o -name "*.db" \) -print0)

      # Copy all client sync blob files
      while IFS= read -r -d '' blob_file; do
        rel_path="${blob_file#"${PROD_DATA_DIR}/user-files/"}"
        dest_blob="${STAGE_DATA_DIR}/user-files/${rel_path}"
        mkdir -p "$(dirname "${dest_blob}")"
        echo "[+] Copying sync blob: user-files/${rel_path}..."
        cp "${blob_file}" "${dest_blob}"
      done < <(find "${PROD_DATA_DIR}/user-files" -type f -name "*.blob" -print0)
    fi
  fi

  # 3. Copy companion metadata (.migrate, config.json)
  if [[ -f "${PROD_DATA_DIR}/.migrate" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would copy .migrate"
    else
      echo "[+] Copying .migrate..."
      cp "${PROD_DATA_DIR}/.migrate" "${STAGE_DATA_DIR}/.migrate"
    fi
  fi

  if [[ -f "${PROD_DATA_DIR}/config.json" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would copy config.json"
    else
      echo "[+] Copying config.json..."
      cp "${PROD_DATA_DIR}/config.json" "${STAGE_DATA_DIR}/config.json"
    fi
  fi

  # 4. Enforce filesystem ownership (UID/GID 1000:1000)
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] would enforce 1000:1000 filesystem ownership on ${STAGE_DATA_DIR}"
  else
    if [[ -n "${CHOWN_CMD:-}" ]]; then
      ${CHOWN_CMD} "${STAGE_DATA_DIR}"
    elif command -v chown >/dev/null 2>&1; then
      if chown -R 1000:1000 "${STAGE_DATA_DIR}" 2>/dev/null; then
        echo "[+] Enforced 1000:1000 ownership on ${STAGE_DATA_DIR}."
      else
        if [[ "$(id -u)" -eq 0 ]]; then
          echo "[-] ERROR: Failed to enforce 1000:1000 ownership on ${STAGE_DATA_DIR}." >&2
          exit 1
        else
          echo "[*] Notice: Non-root execution (UID $(id -u)); skipped chown 1000:1000."
        fi
      fi
    fi
  fi

elif [[ "${SERVICE}" == "vaultwarden" ]]; then
  # 1. Snapshot db.sqlite3
  if [[ -f "${PROD_DATA_DIR}/db.sqlite3" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would snapshot ${PROD_DATA_DIR}/db.sqlite3 to ${STAGE_DATA_DIR}/db.sqlite3"
    else
      dest_db="${STAGE_DATA_DIR}/db.sqlite3"
      rm -f "${dest_db}-wal" "${dest_db}-shm"
      escaped_dest="${dest_db//\'/\'\'}"
      echo "[+] Snapshotting SQLite DB: db.sqlite3..."
      if ! sqlite3 "${PROD_DATA_DIR}/db.sqlite3" ".backup '${escaped_dest}'"; then
        echo "[-] ERROR: SQLite .backup failed for db.sqlite3" >&2
        exit 1
      fi
    fi
  else
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] warning: db.sqlite3 not found in prod directory"
    else
      echo "[-] ERROR: Primary Vaultwarden database not found at ${PROD_DATA_DIR}/db.sqlite3" >&2
      exit 1
    fi
  fi

  # 2. Companion state hydration: rsa_key.pem, rsa_key.pub, attachments/, sends/, config.json
  if [[ -f "${PROD_DATA_DIR}/rsa_key.pem" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would copy rsa_key.pem and chmod 600"
    else
      echo "[+] Copying rsa_key.pem..."
      cp "${PROD_DATA_DIR}/rsa_key.pem" "${STAGE_DATA_DIR}/rsa_key.pem"
      chmod 600 "${STAGE_DATA_DIR}/rsa_key.pem"
    fi
  fi

  if [[ -f "${PROD_DATA_DIR}/rsa_key.pub" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would copy rsa_key.pub"
    else
      echo "[+] Copying rsa_key.pub..."
      cp "${PROD_DATA_DIR}/rsa_key.pub" "${STAGE_DATA_DIR}/rsa_key.pub"
      chmod 644 "${STAGE_DATA_DIR}/rsa_key.pub"
    fi
  fi

  if [[ -d "${PROD_DATA_DIR}/attachments" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would copy attachments directory"
    else
      echo "[+] Copying attachments directory..."
      mkdir -p "${STAGE_DATA_DIR}/attachments"
      cp -R "${PROD_DATA_DIR}/attachments/." "${STAGE_DATA_DIR}/attachments/"
    fi
  fi

  if [[ -d "${PROD_DATA_DIR}/sends" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would copy sends directory"
    else
      echo "[+] Copying sends directory..."
      mkdir -p "${STAGE_DATA_DIR}/sends"
      cp -R "${PROD_DATA_DIR}/sends/." "${STAGE_DATA_DIR}/sends/"
    fi
  fi

  if [[ -f "${PROD_DATA_DIR}/config.json" ]]; then
    if [[ "${DRY_RUN}" == "true" ]]; then
      echo "[dry-run] would copy config.json"
    else
      echo "[+] Copying config.json..."
      cp "${PROD_DATA_DIR}/config.json" "${STAGE_DATA_DIR}/config.json"
    fi
  fi
fi

# ------------------------------------------------------------------------------
# Integrity Verification
# ------------------------------------------------------------------------------
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[dry-run] would run PRAGMA integrity_check on hydrated databases"
else
  validate_integrity "${STAGE_DATA_DIR}"
fi

# ------------------------------------------------------------------------------
# Post-Hydration Container Boot (--start)
# ------------------------------------------------------------------------------
if [[ "${DO_START}" == "true" ]]; then
  echo "[+] Starting staging container '${CONTAINER_NAME}'..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] would run: ${DOCKER_BIN} compose -f ${COMPOSE_FILE} --profile staging up -d ${CONTAINER_NAME}"
  else
    if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
      echo "[-] ERROR: Docker executable '${DOCKER_BIN}' not found in PATH." >&2
      exit 1
    fi
    "${DOCKER_BIN}" compose -f "${COMPOSE_FILE}" --profile staging up -d "${CONTAINER_NAME}"
    echo "[+] Staging container '${CONTAINER_NAME}' started successfully."
  fi
fi

echo "[+] Staging hydration for '${SERVICE}' completed successfully!"
exit 0
