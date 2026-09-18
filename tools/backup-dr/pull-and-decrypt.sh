#!/usr/bin/env bash
# ==============================================================================
# Disaster Recovery (DR): Automated Backup Pull & Decryption Engine
# ==============================================================================
# Discovers and pulls the newest encrypted backup archive for a service from
# Backblaze B2, AWS S3, or local storage; verifies the OpenSSL Salted__ magic
# header (first 8 bytes); and decrypts it into a target or temporary scratchpad
# directory using POSIX-standard OpenSSL AES-256-CBC PBKDF2 (100k iterations).
#
# Features:
# - Strict shell safety (set -euo pipefail)
# - Guaranteed temporary scratchpad cleanup on EXIT/INT/TERM via trap (unless --keep)
# - Pre-decryption OpenSSL 'Salted__' magic header integrity verification
# - B2 / S3 remote backup discovery via rclone or aws CLI
# - Offline & local directory scanning for latest timestamped archive
# - Supports BACKUP_PASSPHRASE with fallback to BACKUP_ENCRYPTION_KEY or --passphrase
# - Safe dry-run mode for pre-flight DR readiness validation
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Defaults & Initialization
# ------------------------------------------------------------------------------
SERVICE_NAME="${SERVICE_NAME:-}"
SOURCE="${SOURCE:-${BACKUP_SOURCE:-}}"
BACKUP_DIR="${BACKUP_DIR:-}"
ARCHIVE_FILE="${ARCHIVE_FILE:-${BACKUP_FILE:-}}"
DEST_DIR="${DEST_DIR:-}"
CLI_PASSPHRASE=""
DRY_RUN=false
KEEP=false

# Scratchpad lifecycle tracking
SCRATCH_DIR="$(mktemp -d /tmp/dr-decrypt-XXXXXX)"

cleanup() {
  local exit_code=$?
  if [[ "${KEEP}" == "true" ]]; then
    if [[ -d "${SCRATCH_DIR}" ]]; then
      echo "[*] Retention enabled (--keep): temporary files retained at ${SCRATCH_DIR}"
    fi
  else
    if [[ -n "${SCRATCH_DIR}" && -d "${SCRATCH_DIR}" ]]; then
      rm -rf "${SCRATCH_DIR}"
    fi
  fi
  return "${exit_code}"
}
trap cleanup EXIT INT TERM

# ------------------------------------------------------------------------------
# Help & Usage
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Discovers, verifies, and decrypts encrypted backup archives for self-hosted services.

Options:
  -s, --service <name>       Service name (e.g. actual, vaultwarden, homeassistant)
      --source <type>        Archive source: b2, s3, local, file
  -b, --backup-dir <path>    Directory containing local backup archives (default: /backups)
  -f, --file <path>          Path to a specific backup archive file to decrypt
  -d, --dest <path>          Destination directory for extracted contents
  -p, --passphrase <val>     Decryption passphrase (overrides env vars)
      --dry-run              Discover and validate archive header without decrypting
  -k, --keep                 Keep temporary scratchpad directory after exit
  -h, --help                 Display this help message and exit

Environment Variables:
  SERVICE_NAME               Service name (e.g. actual, vaultwarden)
  BACKUP_SOURCE              Backup source type (b2, s3, local, file)
  BACKUP_DIR                 Directory containing local backup archives
  BACKUP_FILE                Specific backup archive file to decrypt
  DEST_DIR                   Destination directory for extracted contents
  BACKUP_PASSPHRASE          Primary decryption passphrase
  BACKUP_ENCRYPTION_KEY      Fallback decryption passphrase
  BACKUP_DEST_BUCKET         S3/B2 bucket name
  BACKUP_DEST_ENDPOINT       S3/B2 endpoint URL
  BACKUP_DEST_PREFIX         S3/B2 object prefix (defaults to backups/\${SERVICE_NAME})
  BACKUP_DEST_ACCESS_KEY_ID  S3/B2 Access Key ID
  BACKUP_DEST_SECRET_ACCESS_KEY S3/B2 Secret Access Key
EOF
}

# ------------------------------------------------------------------------------
# Parse CLI Arguments
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--service)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      SERVICE_NAME="$2"
      shift 2
      ;;
    --source)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      SOURCE="$2"
      shift 2
      ;;
    -b|--backup-dir)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      BACKUP_DIR="$2"
      shift 2
      ;;
    -f|--file)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      ARCHIVE_FILE="$2"
      shift 2
      ;;
    -d|--dest)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      DEST_DIR="$2"
      shift 2
      ;;
    -p|--passphrase)
      if [[ -z "${2:-}" ]]; then
        echo "[-] ERROR: Missing value for $1" >&2
        exit 1
      fi
      CLI_PASSPHRASE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -k|--keep)
      KEEP=true
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
# Source Detection & Parameter Validation
# ------------------------------------------------------------------------------
if [[ -z "${SOURCE}" ]]; then
  if [[ -n "${ARCHIVE_FILE}" ]]; then
    SOURCE="file"
  elif [[ -n "${BACKUP_DIR}" ]]; then
    SOURCE="local"
  elif [[ -n "${BACKUP_DEST_BUCKET:-}" ]]; then
    SOURCE="b2"
  else
    SOURCE="local"
  fi
fi

case "${SOURCE}" in
  file)
    if [[ -z "${ARCHIVE_FILE}" ]]; then
      echo "[-] ERROR: --file <path> is required when source is 'file'." >&2
      exit 1
    fi
    if [[ ! -f "${ARCHIVE_FILE}" ]]; then
      echo "[-] ERROR: Specified archive file '${ARCHIVE_FILE}' does not exist." >&2
      exit 1
    fi
    ;;

  local)
    if [[ -z "${SERVICE_NAME}" && -z "${ARCHIVE_FILE}" ]]; then
      echo "[-] ERROR: --service <name> or --file <path> is required for local backup discovery." >&2
      exit 1
    fi
    if [[ -z "${BACKUP_DIR}" ]]; then
      if [[ -d "/backups" ]]; then
        BACKUP_DIR="/backups"
      else
        echo "[-] ERROR: --backup-dir <path> is required for local source." >&2
        exit 1
      fi
    fi
    if [[ ! -d "${BACKUP_DIR}" ]]; then
      echo "[-] ERROR: Local backup directory '${BACKUP_DIR}' does not exist." >&2
      exit 1
    fi
    ;;

  b2|s3)
    if [[ -z "${SERVICE_NAME}" ]]; then
      echo "[-] ERROR: --service <name> is required when querying B2/S3." >&2
      exit 1
    fi
    if [[ -z "${BACKUP_DEST_BUCKET:-}" ]]; then
      echo "[-] ERROR: BACKUP_DEST_BUCKET environment variable must be set for B2/S3 queries." >&2
      exit 1
    fi
    if ! command -v rclone >/dev/null 2>&1 && ! command -v aws >/dev/null 2>&1; then
      echo "[-] ERROR: Neither 'rclone' nor 'aws' CLI tools are available in PATH." >&2
      exit 1
    fi
    ;;

  *)
    echo "[-] ERROR: Unsupported source '${SOURCE}'. Valid sources are: b2, s3, local, file." >&2
    exit 1
    ;;
esac

# ------------------------------------------------------------------------------
# Archive Integrity Validation: OpenSSL Salted__ Header Check
# ------------------------------------------------------------------------------
validate_magic_header() {
  local target_file="$1"
  if [[ ! -f "${target_file}" ]]; then
    echo "[-] ERROR: Archive file '${target_file}' not found." >&2
    return 1
  fi

  local file_size
  file_size=$(wc -c < "${target_file}" | tr -d ' ')
  if [[ "${file_size}" -lt 16 ]]; then
    echo "[-] ERROR: Archive '${target_file}' is truncated or too small (${file_size} bytes, minimum 16 bytes for OpenSSL header + salt)." >&2
    return 1
  fi

  local magic
  magic=$(head -c 8 "${target_file}" 2>/dev/null || true)
  if [[ "${magic}" != "Salted__" ]]; then
    echo "[-] ERROR: Archive '${target_file}' failed magic header check: missing OpenSSL 'Salted__' header (got '${magic}'). File may be unencrypted, corrupted, or incomplete." >&2
    return 1
  fi

  echo "[+] Magic header verified: OpenSSL 'Salted__' present in '${target_file}'."
  return 0
}

# ------------------------------------------------------------------------------
# Archive Discovery & Download
# ------------------------------------------------------------------------------
TARGET_ARCHIVE=""

if [[ "${SOURCE}" == "file" ]]; then
  TARGET_ARCHIVE="${ARCHIVE_FILE}"
  echo "[+] Using explicit backup archive: ${TARGET_ARCHIVE}"

elif [[ "${SOURCE}" == "local" ]]; then
  echo "[+] Discovering latest backup archive for '${SERVICE_NAME}' in ${BACKUP_DIR}..."

  # Find all matching archives, sort by filename descending to pick newest ISO timestamp
  latest_file=$(find "${BACKUP_DIR}" -type f -name "${SERVICE_NAME}-backup-*.tar.gz.enc" | while IFS= read -r filepath; do
    printf "%s\t%s\n" "$(basename "${filepath}")" "${filepath}"
  done | sort -r -k1,1 | head -n 1 | cut -f2- || true)

  if [[ -z "${latest_file}" || ! -f "${latest_file}" ]]; then
    echo "[-] ERROR: No backup archives matching '${SERVICE_NAME}-backup-*.tar.gz.enc' found in '${BACKUP_DIR}'." >&2
    exit 1
  fi

  TARGET_ARCHIVE="${latest_file}"
  echo "[+] Discovered newest local archive: ${TARGET_ARCHIVE}"

elif [[ "${SOURCE}" == "b2" || "${SOURCE}" == "s3" ]]; then
  dest_prefix="${BACKUP_DEST_PREFIX:-backups/${SERVICE_NAME}}"
  dest_prefix="${dest_prefix#/}"
  dest_prefix="${dest_prefix%/}"

  endpoint="${BACKUP_DEST_ENDPOINT:-}"
  if [[ -n "${endpoint}" && "${endpoint}" != http* ]]; then
    endpoint="https://${endpoint}"
  fi

  echo "[+] Querying remote bucket s3://${BACKUP_DEST_BUCKET}/${dest_prefix}/ for '${SERVICE_NAME}' archives..."

  remote_files=""
  if command -v rclone >/dev/null 2>&1; then
    rclone_endpoint_arg=()
    if [[ -n "${endpoint}" ]]; then
      rclone_endpoint_arg=("--s3-endpoint=${endpoint}")
    fi
    rclone_auth_args=()
    if [[ -n "${BACKUP_DEST_ACCESS_KEY_ID:-}" ]]; then
      rclone_auth_args+=("--s3-access-key-id=${BACKUP_DEST_ACCESS_KEY_ID}")
    fi
    if [[ -n "${BACKUP_DEST_SECRET_ACCESS_KEY:-}" ]]; then
      rclone_auth_args+=("--s3-secret-access-key=${BACKUP_DEST_SECRET_ACCESS_KEY}")
    fi

    remote_files=$(rclone lsf ":s3:${BACKUP_DEST_BUCKET}/${dest_prefix}/" \
      --s3-provider=Other \
      "${rclone_endpoint_arg[@]}" \
      "${rclone_auth_args[@]}" \
      --s3-no-check-bucket 2>/dev/null || true)
  elif command -v aws >/dev/null 2>&1; then
    aws_endpoint_arg=()
    if [[ -n "${endpoint}" ]]; then
      aws_endpoint_arg=("--endpoint-url" "${endpoint}")
    fi

    remote_files=$(AWS_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID:-}" \
      AWS_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY:-}" \
      aws s3 ls "s3://${BACKUP_DEST_BUCKET}/${dest_prefix}/" \
      "${aws_endpoint_arg[@]}" 2>/dev/null | awk '{print $NF}' || true)
  fi

  latest_remote_archive=$(echo "${remote_files}" | grep -E "^${SERVICE_NAME}-backup-.*\.tar\.gz\.enc$" | sort -r | head -n 1 || true)

  if [[ -z "${latest_remote_archive}" ]]; then
    echo "[-] ERROR: No remote backup archives matching '${SERVICE_NAME}-backup-*.tar.gz.enc' found in s3://${BACKUP_DEST_BUCKET}/${dest_prefix}/." >&2
    exit 1
  fi

  echo "[+] Discovered latest remote archive: ${latest_remote_archive}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[+] Dry-run mode: Remote archive 's3://${BACKUP_DEST_BUCKET}/${dest_prefix}/${latest_remote_archive}' verified. Download skipped."
    exit 0
  fi

  downloaded_file="${SCRATCH_DIR}/${latest_remote_archive}"
  echo "[+] Pulling archive to staging: ${downloaded_file}..."

  if command -v rclone >/dev/null 2>&1; then
    rclone copyto ":s3:${BACKUP_DEST_BUCKET}/${dest_prefix}/${latest_remote_archive}" \
      "${downloaded_file}" \
      --s3-provider=Other \
      "${rclone_endpoint_arg[@]}" \
      "${rclone_auth_args[@]}" \
      --s3-no-check-bucket
  else
    AWS_ACCESS_KEY_ID="${BACKUP_DEST_ACCESS_KEY_ID:-}" \
    AWS_SECRET_ACCESS_KEY="${BACKUP_DEST_SECRET_ACCESS_KEY:-}" \
    aws s3 cp "s3://${BACKUP_DEST_BUCKET}/${dest_prefix}/${latest_remote_archive}" \
      "${downloaded_file}" \
      "${aws_endpoint_arg[@]}"
  fi

  TARGET_ARCHIVE="${downloaded_file}"
fi

# ------------------------------------------------------------------------------
# Pre-Decryption Integrity Check
# ------------------------------------------------------------------------------
validate_magic_header "${TARGET_ARCHIVE}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[+] Dry-run successful: Archive '${TARGET_ARCHIVE}' is verified intact. Decryption skipped."
  exit 0
fi

# ------------------------------------------------------------------------------
# Passphrase Resolution
# ------------------------------------------------------------------------------
PASSPHRASE_VAR=""
if [[ -n "${CLI_PASSPHRASE}" ]]; then
  BACKUP_PASSPHRASE="${CLI_PASSPHRASE}"
  export BACKUP_PASSPHRASE
  PASSPHRASE_VAR="BACKUP_PASSPHRASE"
elif [[ -n "${BACKUP_PASSPHRASE:-}" ]]; then
  export BACKUP_PASSPHRASE
  PASSPHRASE_VAR="BACKUP_PASSPHRASE"
elif [[ -n "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
  export BACKUP_ENCRYPTION_KEY
  PASSPHRASE_VAR="BACKUP_ENCRYPTION_KEY"
else
  echo "[-] ERROR: Decryption passphrase missing. Set BACKUP_PASSPHRASE, BACKUP_ENCRYPTION_KEY, or pass --passphrase." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Decryption & Unpacking
# ------------------------------------------------------------------------------
OUTPUT_DEST="${DEST_DIR}"
if [[ -z "${OUTPUT_DEST}" ]]; then
  OUTPUT_DEST="${SCRATCH_DIR}/extracted"
fi
mkdir -p "${OUTPUT_DEST}"

echo "[+] Decrypting archive using OpenSSL AES-256-CBC PBKDF2 (100,000 iterations)..."

if ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -in "${TARGET_ARCHIVE}" -pass "env:${PASSPHRASE_VAR}" | tar -xz -C "${OUTPUT_DEST}"; then
  echo "[-] ERROR: Decryption or tar extraction failed for archive '${TARGET_ARCHIVE}'." >&2
  exit 1
fi

extracted_count=$(find "${OUTPUT_DEST}" -type f | wc -l | tr -d ' ')
echo "[+] Decryption and extraction completed successfully: ${extracted_count} file(s) extracted to ${OUTPUT_DEST}."

if [[ -z "${DEST_DIR}" ]]; then
  echo "[+] Isolated scratchpad verification complete."
fi

exit 0
