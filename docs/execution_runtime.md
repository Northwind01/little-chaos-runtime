# LittleChaos Execution Runtime

This package is a high-level orchestration layer above the existing GR00T + SONIC stack. It does not replace teleop, MuJoCo, recording, collision supervision, or policy inference internals.

## Architecture

The intended control flow is:

`CLI -> ExecutionRuntime -> PlannerBackend -> SkillRegistry -> SkillExecutor -> (GrootClient | SonicClient) -> SonicCommandGateway -> SONIC`

Supporting read-only inputs:

- `WorldState` / `CompositeWorld` for ego RGB and privileged state
- `SuccessDetector` for semantic success checks
- `TaskLogger` for structured JSONL episode logs
- `ControlGate` for autonomous-vs-teleop command ownership
- `SonicCommandGateway` as the only autonomous binder of `:5556`

```text
Autonomous session
  ExecutionRuntime  --set_active GROOT|LOCOMOTION|NONE-->  SonicCommandGateway
  SonicClient (locomotion)  --submit packed planner-->     SonicCommandGateway
  run_vla_inference         --PUB.connect packed pose-->   SonicCommandGateway ingest :5561
  SonicCommandGateway       --PUB bind :5556-->            SONIC ZMQManager SUB

  run_sonic_scene           --PUB :5555 ego RGB-->         CompositeWorld
  run_sonic_scene           --PUB :5559 privileged-->      CompositeWorld
  SONIC                     --PUB :5557 g1_debug-->        yaw fallback
```

## Session modes

Teleop and autonomous execution are separate. Never start both.

**Teleop (unchanged):** `make teleop` / `pico_manager_thread_server.py` binds `:5556`. Do not start the runtime gateway. Packed pose / planner traffic stays on the existing pico path.

**Autonomous:** sim + controller + policy + inference-in-connect-mode + runtime shell. The runtime's `SonicCommandGateway` binds `:5556`. Startup fails if pico, leftover bind-mode inference, or any other process already owns that port.

Do not run `pico_manager`, default bind-mode `make inference`, or `keyboard.sh` with the autonomous runtime.

## SonicCommandGateway

Transport multiplexing and control ownership only. Not a planner.

- PUB-binds `:5556` (SONIC already SUB-connects here)
- SUB-binds GROOT ingest `:5561` (`SONIC_GROOT_INGEST_PORT`)
- In-process locomotion `submit()` from `SonicClient`
- Active source is exactly one of `GROOT`, `LOCOMOTION`, `NONE`
- Packets from the inactive source are dropped
- `publish_control()` is runtime-only, for idle / PLANNER vs POSE `command` messages during source transitions

`ExecutionRuntime` owns logical arbitration:

- `vla.*` acquires `GROOT`
- `locomotion.*` acquires `LOCOMOTION`
- skill end, task end, and `:stop` acquire `NONE`

On each transition: cancel the previous producer, set `NONE` (drop stale packets), send idle + mode control packets, then activate the new source.

## Ports

| Port | Role |
| --- | --- |
| 5555 | Ego RGB (clean recorded / VLA view) |
| 5556 | SONIC commands — pico in teleop, gateway in autonomous |
| 5557 | `g1_debug` robot state (yaw/quat; no live XY) |
| 5558 | Operator HUD RGB |
| 5559 | Observational privileged snapshot (XY, girl, collision, fallen) |
| 5561 | GROOT ingest into the gateway (autonomous only) |
| 5580 | Keyboard `prompt:` / `p` — runtime PUB-binds this in autonomous mode |
| 5550 | GR00T PolicyServer |

## Package Responsibilities

`little_chaos/runtime/` — contracts, state machine, ownership, orchestrator, JSONL logs

`little_chaos/planner/` — `MockPlanner` / `VestaPlanner`, structured JSON parse

`little_chaos/skills/` — registry and executors (`vla.find_girl`, `vla.go_to_girl`, `locomotion.walk|stop|retreat|turn_around`)

`little_chaos/backends/` — `GrootClient`, `SonicClient`, `SonicCommandGateway`

`little_chaos/evaluation/` — VLM success detector and ground-truth observer (never command the robot)

`little_chaos/world/` — ego RGB, privileged ZMQ, CompositeWorld

`little_chaos/cli/` — factory + `python -m little_chaos.cli.shell`

## Runtime State Machine

`IDLE -> PLAN -> START_SKILL -> RUNNING -> STOP_SKILL -> PLAN`

- Planner chooses one next skill
- Skill calls are validated against `SkillRegistry`
- VLA skills do not self-declare success; the detector does
- `:stop` bypasses the planner and forces `NONE` + safe idle
- Collision or fallen veto aborts locomotion

## Skills

Registered names (see `:skills` in the shell). Planner output must use these exactly.

| Skill | Args | Notes |
| --- | --- | --- |
| `vla.find_girl` | (none) | Canonical GR00T prompt `"Find the girl"` |
| `vla.go_to_girl` | (none) | Canonical GR00T prompt `"Go to the girl"` |
| `locomotion.walk` | `direction`, `speed`, `duration_s` | See enums below |
| `locomotion.stop` | (none) | SONIC idle |
| `locomotion.turn_around` | (none) | Closed-loop ~180° yaw |
| `locomotion.retreat` | `distance_m` (required) | Closed-loop backward XY |

`locomotion.walk` arguments:

- `direction`: `forward` \| `backward` \| `left` \| `right` (default `forward`)
- `speed`: `slow` \| `normal` (default `slow`)
- `duration_s`: number, default `1.0`, capped by `WALK_MAX_DURATION_S` (default 5)

`locomotion.retreat` `distance_m` is required and clamped to `[RETREAT_MIN_M, RETREAT_MAX_M]` (default 0.1–1.0).

VLA skills do not self-declare success; the success detector does. Collision or fallen veto aborts locomotion.

## How to run

### Offline / demo (no sim)

Uses mock planner, simulated world, and a demo success detector. No ZMQ.

```bash
cd /path/to/little-chaos-runtime
make shell
```

### Live autonomous — one-shot tmux (recommended)

Starts **sim + controller + policy + runtime + connect-mode inference**. Does **not** start teleop/pico, `make keyboard`, or bind-mode inference (`:5556` stays free for the gateway).

```bash
cd /path/to/little-chaos-runtime
make live MODEL=/checkpoints/<your_ckpt> PROMPT='Find the girl.' SCENARIO=little_chaos
```

Optional Make vars: `LAB_ROOT` (default `../gr00t-wbc-lab`), `SESSION_NAME` (default `littlechaos`), `WITH_CONTAINERS=0`, `ATTACH=0`.

Tear down:

```bash
make live-down
```

Focus the **runtime** pane. On the first VLA skill the runtime:

1. `enable_planner` (latches SONIC `operator_state.start` — required; pose-only never starts the loop)
2. `enable_pose` (STREAMED MOTION for GR00T tokens)
3. keyboard `i` (initial pose) then `prompt:` / `p` to inference

In the **controller** pane you should see `[Control] DEBUG: operator_state.start=true` and then `g1_debug` traffic so inference stops saying `waiting for state msg`.

Episode end idles SONIC with planner IDLE; it does **not** send `stop=True` (that would exit G1Deploy).

### Live autonomous — manual

1. Start sim + controller + policy (`:5556` free).
2. Activate WBC `.venv_sim` and set `PYTHONPATH` to lab `src/` + WBC checkout.
3. Start the runtime shell (`LITTLECHAOS_LIVE=1`) — it binds `:5556` and `:5580`.
4. Start inference in connect mode: `LITTLECHAOS_RUNTIME=1 make inference ...`

```bash
export LAB_ROOT=/path/to/gr00t-wbc-lab
export WBC_DIR="$LAB_ROOT/external/GR00T-WholeBodyControl"
source "$WBC_DIR/.venv_sim/bin/activate"
export PYTHONPATH="$LAB_ROOT/src:$WBC_DIR${PYTHONPATH:+:$PYTHONPATH}"
export LITTLECHAOS_LIVE=1
python -m little_chaos.cli.shell
```

```bash
LITTLECHAOS_RUNTIME=1 make -C "$LAB_ROOT" inference PROMPT='Find the girl'
```

## Shell commands

Lines starting with `:` are meta-commands. Everything else is a **task string** for the planner.

| Command | Meaning |
| --- | --- |
| `:help` | List shell commands |
| `:tasks` | List mock-planner phrases (when `PLANNER_BACKEND=mock`) |
| `:skills` | List registered skill names |
| `:status` | Runtime state, active skill, command source, sensors |
| `:stop` | Cancel the current episode; force command source `NONE` |
| `:quit` / `:exit` | Stop episode (if any) and leave the shell |

Typing a new task while one is running cancels the active episode first, then starts the new one.

Episode outcomes printed by the shell: `success`, `failure`, `cancelled`, `cannot_complete`.

## Allowed task phrases (mock planner)

Default `PLANNER_BACKEND=mock`. Matching is case-insensitive; punctuation is stripped. Unknown phrases return `cannot_complete` immediately.

| You type | Skills run (in order) |
| --- | --- |
| `find the girl` | `vla.find_girl` → `vla.go_to_girl` |
| `find girl` | same |
| `find the girl and go to her` | same |
| `find girl and go to her` | same |
| `go to the girl` | `vla.go_to_girl` |
| `turn around and walk away` | `locomotion.turn_around` → `locomotion.walk` |
| `find the girl approach her retreat then stop` | find → go → `locomotion.retreat` → `locomotion.stop` |
| `find the girl go to her turn around retreat half a meter stop` | find → go → turn → retreat → stop |

List live with `:tasks`. For open-ended language, set `PLANNER_BACKEND=vesta` plus `VESTA_ENDPOINT` / `VESTA_MODEL` (still must emit validated skill JSON).

## Common failures

| Symptom | Fix |
| --- | --- |
| `pyzmq is required...` | Use WBC `.venv_sim` (or install `.[live]`) |
| `vr_camera_bridge is not importable` | `PYTHONPATH` needs `$LAB_ROOT/src` |
| `Cannot import gear_sonic...` | Use `.venv_sim` + WBC on `PYTHONPATH` |
| `No camera frames from ...:5555` | Start sim first; `session-down` kills publishers |
| `:5556` already bound / ownership error | Stop pico / bind-mode inference |
| `cannot_complete` / mock has no sequence | Use a phrase from `:tasks` |
| Inference `Pausing...` / waiting for state | Control loop not started (`enable_planner` first), or robot fallen, or controller dead. Look for `operator_state.start=true` in controller |
| Controller pane dies after episode / `Stopping G1Deploy` | Fixed: do not send ZMQ `stop=True` on idle. Restart session if you still see this on old code |
| Episode `success` with no robot motion (live, no VLM) | Old `DemoDetector` faked success; live now waits until VLA timeout unless `VLM_ENDPOINT` is set |
| Mode switches but robot never stands / no `g1_debug` | `enable_pose` alone is not enough; need planner start first (fixed in orchestrator) |

## Tests

```bash
python3 -m pytest -c pyproject.toml tests
```

The tests avoid GPU, MuJoCo, and Vesta. They cover planner validation, skill arguments, gateway source filtering, ownership failure when `:5556` is busy, privileged payload parse, factory live vs offline, mock end-to-end flow, and manual stop.

## Architectural Rules

- Vesta/planner code must not import SONIC internals
- Success detectors must never send robot commands
- High-level planner output must be structured and validated before execution
- Do not duplicate GR00T/SONIC infrastructure when a thin adapter is sufficient
- Keep high-latency planner/detector work off the control thread
- Do not route PICO teleop through the gateway
