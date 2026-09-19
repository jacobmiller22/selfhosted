#!/usr/bin/env bash
# ==============================================================================
# Outside-In Remote Deployment Verification Protocol (ODVP) Smoke Harness
# ==============================================================================
# Automates the 5-layer deployment verification model:
#   L1: Container Stability & Healthcheck Latch (Remote via SSH)
#   L2: Internal Business Logic & Data Probe (Remote via SSH)
#   L3: Reverse Proxy & Bridge Network Verification (Remote via SSH)
#   L4: Outside DNS & TLS Handshake Validation (Client Workstation)
#   L5: Outside-In HTTPS Egress Probe (Client Workstation)
#
# Flags:
#   --host <host>          Target remote host (default: bjorn)
#   --service <name>       Remote container name (e.g. actual, homeassistant)
#   --internal-port <port> Internal container listening port (e.g. 5006)
#   --url <https-url>      Public HTTPS URL (e.g. https://actual.cloud.jacobmiller22.com)
#   --skip-remote          Skip L1-L3 remote SSH checks (client-only L4-L5)
#   --dry-run              Print planned commands without executing
#   --help, -h             Show usage information
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# shellcheck disable=SC2029
# Default Settings
# ------------------------------------------------------------------------------
HOST="bjorn"
SERVICE=""
INTERNAL_PORT=""
URL=""
SKIP_REMOTE=false
DRY_RUN=false

# ------------------------------------------------------------------------------
# Help & Usage Display
# ------------------------------------------------------------------------------
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Outside-In Remote Deployment Verification Protocol (ODVP) automated smoke harness.
Verifies service health across 5 operational layers from container runtime to client HTTPS egress.

Layers:
  L1: Container Stability & Healthcheck Latch (Remote via SSH)
  L2: Internal Business Logic & Data Probe (Remote via SSH)
  L3: Reverse Proxy & Bridge Network Verification (Remote via SSH)
  L4: Outside DNS & TLS Handshake Validation (Client Workstation)
  L5: Outside-In HTTPS Egress Probe (Client Workstation)

Options:
  --host <host>          Target remote host (default: bjorn)
  --service <name>       Remote container name (e.g., actual, homeassistant, vaultwarden)
  --internal-port <port> Internal container port (e.g., 5006, 8123, 7277)
  --url <https-url>      Public HTTPS endpoint (e.g., https://actual.cloud.jacobmiller22.com)
  --skip-remote          Skip L1-L3 remote SSH checks (client-only L4-L5 verification)
  --dry-run              Simulate verification steps without executing network/SSH calls
  -h, --help             Show this help message and exit

Examples:
  # Full 5-layer verification for Actual Budget:
  $(basename "$0") --host bjorn --service actual --internal-port 5006 --url https://actual.cloud.jacobmiller22.com

  # Client-side outside-in verification only:
  $(basename "$0") --skip-remote --url https://actual.cloud.jacobmiller22.com

  # Dry-run execution:
  $(basename "$0") --service actual --internal-port 5006 --url https://actual.cloud.jacobmiller22.com --dry-run
EOF
}

# ------------------------------------------------------------------------------
# CLI Argument Parsing
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "Error: --host requires a non-empty argument." >&2
        exit 1
      fi
      HOST="$2"
      shift 2
      ;;
    --service)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "Error: --service requires a non-empty argument." >&2
        exit 1
      fi
      SERVICE="$2"
      shift 2
      ;;
    --internal-port)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "Error: --internal-port requires a non-empty argument." >&2
        exit 1
      fi
      INTERNAL_PORT="$2"
      shift 2
      ;;
    --url)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "Error: --url requires a non-empty argument." >&2
        exit 1
      fi
      URL="$2"
      shift 2
      ;;
    --skip-remote)
      SKIP_REMOTE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "Error: Unknown argument: $1" >&2
      show_help >&2
      exit 1
      ;;
  esac
done

# ------------------------------------------------------------------------------
# Input Validation
# ------------------------------------------------------------------------------
if [[ -z "$SERVICE" && -z "$URL" ]]; then
  echo "Error: At least one of --service <name> or --url <https-url> must be provided." >&2
  show_help >&2
  exit 1
fi

if [[ "$SKIP_REMOTE" == true && -z "$URL" ]]; then
  echo "Error: --url <https-url> is required when --skip-remote is specified." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Dry Run Execution Path
# ------------------------------------------------------------------------------
if [[ "$DRY_RUN" == true ]]; then
  echo "=============================================================================="
  echo "🚀 [DRY-RUN] Outside-In Deployment Verification Protocol (ODVP)"
  echo "=============================================================================="
  if [[ "$SKIP_REMOTE" != true ]]; then
    echo "[DRY-RUN] Pre-flight: ssh -o BatchMode=yes -o ConnectTimeout=5 $HOST 'echo ok'"
    if [[ -n "$SERVICE" ]]; then
      echo "[DRY-RUN] [L1] Stability & Healthcheck: ssh $HOST \"docker inspect --format '{{.State.Status}}' '$SERVICE'\""
      echo "[DRY-RUN] [L1] Restart Loop Check: ssh $HOST \"docker inspect --format '{{.State.RestartCount}}' '$SERVICE'\""
    fi
    if [[ -n "$INTERNAL_PORT" ]]; then
      echo "[DRY-RUN] [L2] Internal Endpoint Probe: ssh $HOST \"curl -fsS http://localhost:$INTERNAL_PORT/\""
    fi
    if [[ -n "$SERVICE" ]]; then
      echo "[DRY-RUN] [L3] Network & Reverse Proxy: ssh $HOST \"docker inspect --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}' '$SERVICE'\""
    fi
  else
    echo "[DRY-RUN] Remote checks skipped (--skip-remote)."
  fi

  if [[ -n "$URL" ]]; then
    echo "[DRY-RUN] [L4] DNS & TLS Handshake: resolve domain and curl -vI $URL"
    echo "[DRY-RUN] [L5] Outside-In HTTPS Egress Probe: curl -fsS -o /dev/null -w '%{http_code}' $URL"
  fi
  echo "=============================================================================="
  echo "✅ [DRY-RUN] Verification plan validated successfully."
  echo "=============================================================================="
  exit 0
fi

# ------------------------------------------------------------------------------
# Remote Host Verification & Pre-flight
# ------------------------------------------------------------------------------
if [[ "$SKIP_REMOTE" != true ]]; then
  echo "==> Verifying remote host reachability: $HOST..."
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "echo ok" >/dev/null 2>&1; then
    echo "ERROR: Remote host '$HOST' is unreachable via SSH." >&2
    exit 2
  fi
  echo "    Remote host '$HOST' is reachable."
fi

# ------------------------------------------------------------------------------
# Layer 1: Container Stability & Healthcheck Latch (Remote)
# ------------------------------------------------------------------------------
if [[ "$SKIP_REMOTE" != true && -n "$SERVICE" ]]; then
  echo "==> [L1] Verifying Container Stability & Healthcheck Latch on '$HOST'..."
  # shellcheck disable=SC2029
  STATUS=$(ssh "$HOST" "docker inspect --format '{{.State.Status}}' '$SERVICE' 2>/dev/null" || echo "not_found")
  if [[ "$STATUS" != "running" ]]; then
    echo "ERROR: [L1 Failure] Container '$SERVICE' status is '$STATUS' (expected 'running')." >&2
    exit 10
  fi

  # shellcheck disable=SC2029
  RESTARTS=$(ssh "$HOST" "docker inspect --format '{{.State.RestartCount}}' '$SERVICE' 2>/dev/null" || echo "0")
  # shellcheck disable=SC2029
  HEALTH=$(ssh "$HOST" "docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' '$SERVICE' 2>/dev/null" || echo "none")

  if [[ "$HEALTH" == "unhealthy" ]]; then
    echo "ERROR: [L1 Failure] Container '$SERVICE' healthcheck status is 'unhealthy'." >&2
    exit 11
  fi
  echo "    [L1 PASS] Container '$SERVICE' is running (health: $HEALTH, restarts: $RESTARTS)."
fi

# ------------------------------------------------------------------------------
# Layer 2: Internal Business Logic & Data Probe (Remote)
# ------------------------------------------------------------------------------
if [[ "$SKIP_REMOTE" != true && -n "$INTERNAL_PORT" ]]; then
  echo "==> [L2] Probing Internal Business Logic Endpoint on '$HOST' (port $INTERNAL_PORT)..."
  # shellcheck disable=SC2029
  HTTP_CODE=$(ssh "$HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 10 'http://localhost:${INTERNAL_PORT}/' 2>/dev/null || echo '000'")
  if [[ "$HTTP_CODE" == "000" ]]; then
    # Fallback to https in case internal listener requires TLS
  # shellcheck disable=SC2029
    HTTP_CODE=$(ssh "$HOST" "curl -k -s -o /dev/null -w '%{http_code}' --max-time 10 'https://localhost:${INTERNAL_PORT}/' 2>/dev/null || echo '000'")
  fi

  if [[ "$HTTP_CODE" == "000" ]]; then
    echo "ERROR: [L2 Failure] Internal port $INTERNAL_PORT on '$HOST' refused connection (HTTP code 000)." >&2
    exit 20
  fi
  echo "    [L2 PASS] Internal port $INTERNAL_PORT responded with HTTP code $HTTP_CODE."
fi

# ------------------------------------------------------------------------------
# Layer 3: Reverse Proxy & Bridge Network Verification (Remote)
# ------------------------------------------------------------------------------
if [[ "$SKIP_REMOTE" != true && -n "$SERVICE" ]]; then
  echo "==> [L3] Verifying Reverse Proxy & Bridge Network Connectivity on '$HOST'..."
  # shellcheck disable=SC2029
  NETWORKS=$(ssh "$HOST" "docker inspect --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}} {{end}}' '$SERVICE' 2>/dev/null" || echo "")
  if [[ -z "$NETWORKS" ]]; then
    echo "ERROR: [L3 Failure] Container '$SERVICE' has no active network attachments." >&2
    exit 30
  fi

  PROXY_CONTAINER=$(ssh "$HOST" "docker ps --filter 'name=nginx-proxy-manager' --filter 'name=proxy' --format '{{.Names}}' 2>/dev/null | head -n 1" || echo "")
  if [[ -n "$PROXY_CONTAINER" ]]; then
    echo "    [L3 PASS] Container '$SERVICE' attached to networks: [${NETWORKS% }] (Proxy container active: $PROXY_CONTAINER)."
  else
    echo "    [L3 PASS] Container '$SERVICE' attached to networks: [${NETWORKS% }]."
  fi
fi

# ------------------------------------------------------------------------------
# Layer 4: Outside DNS & TLS Handshake Validation (Client Workstation)
# ------------------------------------------------------------------------------
if [[ -n "$URL" ]]; then
  echo "==> [L4] Validating Outside DNS & TLS Handshake from Client Workstation..."
  DOMAIN="${URL#*://}"
  DOMAIN="${DOMAIN%%/*}"
  DOMAIN="${DOMAIN%%:*}"

  DNS_RESOLVED=false
  if command -v dig >/dev/null 2>&1; then
    DNS_OUTPUT=$(dig +short "$DOMAIN" 2>/dev/null || true)
    if [[ -n "$DNS_OUTPUT" ]]; then
      DNS_RESOLVED=true
    fi
  fi
  if [[ "$DNS_RESOLVED" != true ]] && command -v host >/dev/null 2>&1; then
    if host "$DOMAIN" >/dev/null 2>&1; then
      DNS_RESOLVED=true
    fi
  fi
  if [[ "$DNS_RESOLVED" != true ]] && command -v nslookup >/dev/null 2>&1; then
    if nslookup "$DOMAIN" >/dev/null 2>&1; then
      DNS_RESOLVED=true
    fi
  fi
  if [[ "$DNS_RESOLVED" != true ]] && command -v python3 >/dev/null 2>&1; then
    if python3 -c "import socket, sys; sys.exit(0 if socket.gethostbyname('$DOMAIN') else 1)" >/dev/null 2>&1; then
      DNS_RESOLVED=true
    fi
  fi

  if [[ "$DNS_RESOLVED" != true ]]; then
    echo "ERROR: [L4 Failure] DNS resolution failed for domain '$DOMAIN'." >&2
    exit 40
  fi

  TLS_CODE=0
  curl -fsS -I --max-time 15 "$URL" >/dev/null 2>&1 || TLS_CODE=$?
  if [[ "$TLS_CODE" -eq 35 || "$TLS_CODE" -eq 51 || "$TLS_CODE" -eq 60 || "$TLS_CODE" -eq 77 ]]; then
    echo "ERROR: [L4 Failure] TLS handshake or certificate verification failed for '$URL' (curl error code: $TLS_CODE)." >&2
    exit 41
  fi
  echo "    [L4 PASS] DNS resolved for '$DOMAIN' and TLS handshake succeeded."
fi

# ------------------------------------------------------------------------------
# Layer 5: Outside-In HTTPS Egress Probe (Client Workstation)
# ------------------------------------------------------------------------------
if [[ -n "$URL" ]]; then
  echo "==> [L5] Probing Outside-In HTTPS Egress from Client Workstation..."
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$URL" 2>/dev/null || echo "000")

  if [[ "$HTTP_CODE" == "502" ]]; then
    echo "ERROR: [L5 Failure] Egress probe returned HTTP 502 (Bad Gateway). Reverse proxy cannot reach upstream service." >&2
    exit 52
  elif [[ "$HTTP_CODE" == "504" ]]; then
    echo "ERROR: [L5 Failure] Egress probe returned HTTP 504 (Gateway Timeout). Upstream service timed out." >&2
    exit 54
  elif [[ "$HTTP_CODE" == "521" || "$HTTP_CODE" == "522" || "$HTTP_CODE" == "523" || "$HTTP_CODE" == "524" ]]; then
    echo "ERROR: [L5 Failure] Egress probe returned Cloudflare/Origin failure HTTP $HTTP_CODE." >&2
    exit 55
  elif [[ "$HTTP_CODE" == "000" ]]; then
    echo "ERROR: [L5 Failure] Egress probe could not connect to '$URL' (connection failed or timed out)." >&2
    exit 50
  fi

  case "$HTTP_CODE" in
    200|201|204|301|302|303|307|308|401|403)
      echo "    [L5 PASS] Outside HTTPS endpoint '$URL' responded with HTTP status $HTTP_CODE."
      ;;
    *)
      echo "ERROR: [L5 Failure] Outside HTTPS endpoint '$URL' returned unexpected HTTP status $HTTP_CODE." >&2
      exit 51
      ;;
  esac
fi

echo "=============================================================================="
echo "✅ ODVP Verification Passed: All layers verified successfully."
echo "=============================================================================="
exit 0
