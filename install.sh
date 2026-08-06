#!/usr/bin/env bash
#
# Hermes Agent one-shot fix entry point
#
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) <script-name> [hermes-dir]
#
# Examples:
#   bash <(curl -fsSL https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.sh) fix-message-loss
#
# All scripts are idempotent: safe to re-run, auto-backup, rollback on syntax error.
# Compatible with bash 3.2 (macOS default) and bash 4+.

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main"

# Resolve script name -> filename. Uses case instead of associative arrays
# (macOS bash 3.2 does not support them).
resolve_filename() {
  case "${1:-}" in
    fix-message-loss) echo "fix-hermes-desktop-message-loss.py" ;;
    *) echo "" ;;
  esac
}

usage() {
  echo "Usage: bash <(curl -fsSL $REPO_RAW/install.sh) <script-name> [hermes-dir]"
  echo ""
  echo "Available scripts:"
  echo "  fix-message-loss  ->  fix desktop message loss after sleep/shutdown"
  echo ""
  echo "Examples:"
  echo "  bash <(curl -fsSL $REPO_RAW/install.sh) fix-message-loss"
  echo "  bash <(curl -fsSL $REPO_RAW/install.sh) fix-message-loss ~/.hermes/hermes-agent"
  exit 1
}

main() {
  local name="${1:-}"
  local filename
  filename="$(resolve_filename "$name")"
  if [[ -z "$filename" ]]; then
    usage
  fi

  local hermes_dir="${2:-}"

  echo "Downloading $name ($filename) ..."
  local tmp
  tmp="$(mktemp -d)"
  local script_path="$tmp/$filename"

  if ! curl -fsSL "$REPO_RAW/$filename" -o "$script_path"; then
    echo "Download failed: $REPO_RAW/$filename"
    rm -rf "$tmp"
    exit 1
  fi

  echo "Downloaded. Running ..."
  echo ""
  if [[ -n "$hermes_dir" ]]; then
    python3 "$script_path" "$hermes_dir"
  else
    python3 "$script_path"
  fi
  local rc=$?

  rm -rf "$tmp"
  echo ""
  echo "Done. Restart the Hermes desktop app (fully quit, then reopen) to apply the fix."
  exit $rc
}

main "$@"
