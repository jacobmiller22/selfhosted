#!/usr/bin/env bash
set -euo pipefail

# Locate repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TOOL_DIR="$REPO_ROOT/actual/tools/transaction-importer"

cd "$TOOL_DIR"
exec npx tsx src/import-staged.ts "$@"
