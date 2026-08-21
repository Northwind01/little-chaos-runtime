#!/usr/bin/env bash
# Autonomous LittleChaos live stack in one tmux session.
#
# Panes (no teleop / no keyboard / no bind-mode inference):
#   sim | controller
#   policy | runtime | inference (connect-mode → :5561)
#
# Usage (from anywhere):
#   ./scripts/live_session.sh
#   LAB_ROOT=/path/to/gr00t-wbc-lab MODEL=/checkpoints/ckpt \
#     PROMPT='Find the girl.' SCENARIO=little_chaos ./scripts/live_session.sh
#
# Tear down:
#   ./scripts/live_session_down.sh
#   # or: SESSION_NAME=littlechaos make -C "$LAB_ROOT" session-down
set -Eeuo pipefail

RUNTIME_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

# Allow: ./scripts/live_session.sh MODEL=/checkpoints/ckpt PROMPT='Find the girl.'
for arg in "$@"; do
  case "$arg" in
    *=*) export "$arg" ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *) die "unknown arg: $arg (expected KEY=VALUE)" ;;
  esac
done

LAB_ROOT="${LAB_ROOT:-${GR00T_WBC_LAB:-}}"
if [[ -z "$LAB_ROOT" ]]; then
  if [[ -d "$RUNTIME_ROOT/../gr00t-wbc-lab" ]]; then
    LAB_ROOT="$(cd "$RUNTIME_ROOT/../gr00t-wbc-lab" && pwd)"
  else
    die "Set LAB_ROOT to the gr00t-wbc-lab checkout"
  fi
fi
LAB_ROOT="$(cd "$LAB_ROOT" && pwd)"
need_file() { [[ -f "$1" ]] || die "Missing file: $1"; }
need_file "$LAB_ROOT/scripts/common.sh"
# shellcheck disable=SC1091
source "$LAB_ROOT/scripts/common.sh"

backend="${BACKEND:-sonic}"
scenario="${SCENARIO:-little_chaos}"
resolve_scenario "$scenario"
need_file "$SCENARIO_FRAGMENT"

session_name="${SESSION_NAME:-littlechaos}"
with_containers="${WITH_CONTAINERS:-1}"
attach="${ATTACH:-1}"
prompt="${PROMPT:-Find the girl.}"
model="${MODEL:-}"
camera_wait_s="${CAMERA_WAIT_S:-180}"
gateway_wait_s="${GATEWAY_WAIT_S:-180}"

[[ "$backend" == "sonic" ]] || die "BACKEND=sonic only"
[[ -n "$model" ]] || die "Set MODEL=/checkpoints/<checkpoint> (container path)"

need_cmd tmux
need_dir "$WBC_DIR"
need_file "$WBC_DIR/.venv_sim/bin/python"
need_file "$WBC_DIR/.venv_inference/bin/python"

if tmux has-session -t "$session_name" 2>/dev/null; then
  die "tmux session '$session_name' already exists (./scripts/live_session_down.sh first)"
fi

# Refuse to start if something already owns the SONIC command port.
if command -v ss >/dev/null 2>&1; then
  if ss -ltn "sport = :${SONIC_PORT:-5556}" 2>/dev/null | grep -q LISTEN; then
    die "tcp :${SONIC_PORT:-5556} is already bound. Stop pico_manager / bind-mode inference first."
  fi
fi

wait_tcp_snippet() {
  local port="$1"
  local timeout_s="$2"
  local label="$3"
  cat <<EOF
port=$(printf %q "$port")
timeout_s=$(printf %q "$timeout_s")
label=$(printf %q "$label")
echo "[wait] \$label on :\$port (up to \${timeout_s}s)..."
start=\$(date +%s)
while true; do
  ready=0
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn "sport = :\$port" 2>/dev/null | grep -q LISTEN; then
      ready=1
    fi
  elif command -v nc >/dev/null 2>&1; then
    if nc -z 127.0.0.1 "\$port" 2>/dev/null; then
      ready=1
    fi
  elif python -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); ok=s.connect_ex(('127.0.0.1', int(sys.argv[1])))==0; s.close(); sys.exit(0 if ok else 1)" "\$port" 2>/dev/null; then
    ready=1
  fi
  if [[ "\$ready" == "1" ]]; then
    echo "[wait] \$label ready"
    break
  fi
  now=\$(date +%s)
  if (( now - start >= timeout_s )); then
    echo "ERROR: timed out waiting for \$label on :\$port" >&2
    exit 1
  fi
  sleep 1
done
EOF
}

lab_env_exports() {
  cat <<EOF
cd $(printf %q "$LAB_ROOT")
export BACKEND=$(printf %q "$backend")
export SCENARIO=$(printf %q "$scenario")
export PROMPT=$(printf %q "$prompt")
export MODEL=$(printf %q "$model")
export LAB_ROOT=$(printf %q "$LAB_ROOT")
export WBC_DIR=$(printf %q "$WBC_DIR")
export CAMERA_HOST=$(printf %q "$CAMERA_HOST")
export CAMERA_PORT=$(printf %q "$CAMERA_PORT")
export POLICY_PORT=$(printf %q "$POLICY_PORT")
export PRIVILEGED_STATE_PORT=$(printf %q "$PRIVILEGED_STATE_PORT")
export PRIVILEGED_STATE_PUBLISH=$(printf %q "$PRIVILEGED_STATE_PUBLISH")
export SONIC_GROOT_INGEST_HOST=$(printf %q "$SONIC_GROOT_INGEST_HOST")
export SONIC_GROOT_INGEST_PORT=$(printf %q "$SONIC_GROOT_INGEST_PORT")
export DATA_DIR=$(printf %q "$DATA_DIR")
export RUNS_DIR=$(printf %q "$RUNS_DIR")
EOF
}

SIM_CMD="$(
  cat <<EOF
$(lab_env_exports)
echo "======== sim ========"
exec make sim BACKEND=${backend} SCENARIO=${scenario}
EOF
)"

CONTROLLER_CMD="$(
  cat <<EOF
$(lab_env_exports)
echo "======== controller ========"
exec make controller BACKEND=${backend}
EOF
)"

POLICY_CMD="$(
  cat <<EOF
$(lab_env_exports)
echo "======== policy ========"
exec make policy BACKEND=${backend}
EOF
)"

RUNTIME_CMD="$(
  cat <<EOF
$(lab_env_exports)
cd $(printf %q "$RUNTIME_ROOT")
export PYTHONPATH=$(printf %q "$LAB_ROOT/src"):$(printf %q "$WBC_DIR")\${PYTHONPATH:+:\$PYTHONPATH}
export LITTLECHAOS_LIVE=1
export GR00T_WBC_LAB=$(printf %q "$LAB_ROOT")
echo "======== littlechaos runtime ========"
$(wait_tcp_snippet "$CAMERA_PORT" "$camera_wait_s" "ego RGB / MuJoCo camera")
# Give the publisher a moment to emit the first frames.
sleep 2
# Prefer WBC sim venv (gear_sonic + pyzmq).
# shellcheck disable=SC1091
source $(printf %q "$WBC_DIR/.venv_sim/bin/activate")
exec python -m little_chaos.cli.shell
EOF
)"

INFERENCE_CMD="$(
  cat <<EOF
$(lab_env_exports)
export LITTLECHAOS_RUNTIME=1
echo "======== inference (connect-mode → :${SONIC_GROOT_INGEST_PORT}) ========"
$(wait_tcp_snippet "${SONIC_PORT:-5556}" "$gateway_wait_s" "LittleChaos gateway / SONIC commands")
echo "Starting connect-mode inference (does not bind :5556)..."
exec make inference BACKEND=${backend}
EOF
)"

if [[ "$with_containers" == "1" ]]; then
  echo "Starting long-lived containers (make up BACKEND=$backend)..."
  "$LAB_ROOT/scripts/up.sh" "$backend"
fi

state_dir="$RUNS_DIR/sessions"
mkdir -p "$state_dir"
state_file="$state_dir/${session_name}.env"
{
  printf 'SESSION_NAME=%q\n' "$session_name"
  printf 'MUX=%q\n' "tmux"
  printf 'BACKEND=%q\n' "$backend"
  printf 'SCENARIO=%q\n' "$scenario"
  printf 'MODE=%q\n' "littlechaos"
  printf 'RUNTIME_ROOT=%q\n' "$RUNTIME_ROOT"
  printf 'PROMPT=%q\n' "$prompt"
  printf 'MODEL=%q\n' "$model"
} >"$state_file"

help_file="$state_dir/${session_name}.help.txt"
{
  echo "littlechaos autonomous session: $session_name"
  echo "LAB_ROOT=$LAB_ROOT"
  echo "RUNTIME_ROOT=$RUNTIME_ROOT"
  echo "SCENARIO=$scenario  MODEL=$model"
  echo "PROMPT=$prompt"
  echo
  echo "Panes:"
  echo "  sim         make sim          → ego RGB :${CAMERA_PORT}, privileged :${PRIVILEGED_STATE_PORT}"
  echo "  controller  make controller"
  echo "  policy      make policy       → :${POLICY_PORT}"
  echo "  runtime     little_chaos shell (binds SONIC :5556 + keyboard :5580)"
  echo "  inference   LITTLECHAOS_RUNTIME=1 make inference → ingest :${SONIC_GROOT_INGEST_PORT}"
  echo
  echo "Not started (on purpose): teleop/pico, keyboard, bind-mode inference."
  echo
  echo "Runtime pane: type a task, or :skills / :status / :stop"
  echo "Detach: Ctrl-b d"
  echo "Stop:   $RUNTIME_ROOT/scripts/live_session_down.sh"
  echo "        or: SESSION_NAME=$session_name make -C $LAB_ROOT session-down"
} >"$help_file"

echo "Launching tmux session '$session_name'..."
tmux new-session -d -s "$session_name" -n stack -x 220 -y 60 bash -lc "$SIM_CMD"
tmux set-option -t "$session_name" remain-on-exit on
tmux set-option -t "$session_name" mouse on
tmux set-option -t "$session_name" pane-border-status top
tmux set-option -t "$session_name" pane-border-format " #{pane_index}:#{pane_title} "

tmux select-pane -t "$session_name":0.0 -T "sim"
tmux split-window -t "$session_name":0 -h bash -lc "$CONTROLLER_CMD"
tmux select-pane -t "$session_name":0.1 -T "controller"

tmux split-window -t "$session_name":0.0 -v bash -lc "$POLICY_CMD"
tmux select-pane -T "policy"

tmux split-window -t "$session_name":0.1 -v bash -lc "$RUNTIME_CMD"
tmux select-pane -T "runtime"

tmux split-window -t "$session_name":0.3 -v bash -lc "$INFERENCE_CMD"
tmux select-pane -T "inference"

tmux select-layout -t "$session_name":0 tiled
tmux new-window -t "$session_name" -n help bash -lc "cat $(printf %q "$help_file"); echo; exec bash"
tmux select-window -t "$session_name":stack
tmux select-pane -t "$session_name":stack.3

echo "tmux session '$session_name' is up."
echo "Attach:  tmux attach -t $session_name"
echo "Stop:    $RUNTIME_ROOT/scripts/live_session_down.sh"
if [[ "$attach" == "1" && -t 1 && -z "${TMUX:-}" ]]; then
  exec tmux attach -t "$session_name"
fi
