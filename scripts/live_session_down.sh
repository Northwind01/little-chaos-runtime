#!/usr/bin/env bash
# Tear down a session started by scripts/live_session.sh.
set -Eeuo pipefail

RUNTIME_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
session_name="${SESSION_NAME:-littlechaos}"

LAB_ROOT="${LAB_ROOT:-${GR00T_WBC_LAB:-}}"
if [[ -z "$LAB_ROOT" && -d "$RUNTIME_ROOT/../gr00t-wbc-lab" ]]; then
  LAB_ROOT="$(cd "$RUNTIME_ROOT/../gr00t-wbc-lab" && pwd)"
fi

if [[ -n "${LAB_ROOT:-}" && -f "$LAB_ROOT/scripts/session_down.sh" ]]; then
  export SESSION_NAME="$session_name"
  export DOWN_CONTAINERS="${DOWN_CONTAINERS:-0}"
  exec "$LAB_ROOT/scripts/session_down.sh"
fi

echo "Stopping tmux session '$session_name'..."
if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$session_name" 2>/dev/null; then
  tmux kill-session -t "$session_name"
  echo "Killed tmux session '$session_name'."
else
  echo "No tmux session named '$session_name'."
fi
