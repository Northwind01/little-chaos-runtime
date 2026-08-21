# little-chaos-runtime

Turns a natural-language task into a sequence of **skills** (VLA + locomotion) on top of the existing **GR00T + SONIC** lab stack.

It is an orchestration layer — not a replacement for MuJoCo, teleop, recording, or policy inference.

```text
you type a task
    → planner picks the next skill
    → skill runs via GR00T (VLA) or SONIC (walk / turn / …)
    → gateway ensures only one command source talks to SONIC at a time
```

**Sibling repo:** [gr00t-wbc-lab](../gr00t-wbc-lab) owns sim, controller, policy server, and inference. This repo sits above that and drives it in **autonomous** mode.

Teleop (PICO) and autonomous mode must not share SONIC’s command port (`:5556`). Details: [`docs/execution_runtime.md`](docs/execution_runtime.md).

---

## What lives where

```text
little-chaos-runtime/
├── little_chaos/           # Python package
│   ├── cli/                # Shell entry + live/offline wiring (factory)
│   ├── runtime/            # Orchestrator, state machine, ownership, logs
│   ├── planner/            # MockPlanner (default) / VestaPlanner
│   ├── skills/             # Registered skills + executors (vla.*, locomotion.*)
│   ├── backends/           # Thin adapters: GrootClient, SonicClient, gateway
│   ├── world/              # Ego RGB + privileged state (read-only)
│   └── evaluation/         # Success detectors (never command the robot)
├── scripts/                # tmux live session up / down
├── tests/                  # pytest (no GPU / MuJoCo required)
├── docs/                   # Full architecture + runbook
├── Makefile                # make shell | live | live-down | test | help
└── pyproject.toml
```

| Area | Role |
| --- | --- |
| `cli/` | `python -m little_chaos.cli.shell`; builds live vs offline stacks |
| `runtime/` | Episode loop: plan → start skill → run → stop → plan |
| `planner/` | Chooses the next validated skill (or task complete) |
| `skills/` | What the planner is allowed to call |
| `backends/` | ZMQ / SONIC / GR00T adapters only — no planning |
| `world/` | Observations for planners, detectors, closed-loop loco |
| `evaluation/` | Semantic success checks |

Control flow:

`CLI → ExecutionRuntime → Planner → SkillRegistry → SkillExecutor → (GrootClient \| SonicClient) → SonicCommandGateway → SONIC`

---

## Quick start

### Offline demo (no sim)

Mock planner + simulated world. Good for plumbing checks.

```bash
make shell
```

### Live autonomous (sim + SONIC + GR00T)

One tmux session: sim, controller, policy, runtime shell, connect-mode inference. Does **not** start teleop, keyboard, or bind-mode inference.

```bash
make live MODEL=/checkpoints/<your_ckpt> PROMPT='Find the girl.' SCENARIO=little_chaos
```

Tear down:

```bash
make live-down
```

Needs the lab checkout (default `../gr00t-wbc-lab`), WBC `.venv_sim`, and a free `:5556`. See the [runbook](docs/execution_runtime.md#how-to-run) for env / `PYTHONPATH` / failures.

```bash
make help    # all targets
make test    # pytest
```

---

## Using the runtime shell

Focus the **runtime** pane (live) or the offline shell. Lines starting with `:` are commands; everything else is a **task**.

| Input | Meaning |
| --- | --- |
| `:help` | List shell commands |
| `:tasks` | Allowed mock-planner phrases |
| `:skills` | Registered skill names |
| `:status` | State, active skill, command source, sensors |
| `:stop` | Cancel the current episode |
| `:quit` / `:exit` | Leave the shell |
| `find the girl` | Example task (mock → find → go-to) |

Default planner is **mock**: only known phrases work; unknown text returns `cannot_complete`. Use `:tasks`.

---

## Docs

| Doc | Contents |
| --- | --- |
| [`docs/execution_runtime.md`](docs/execution_runtime.md) | Architecture, ports, skills, how to run, shell/tasks, common failures |
| [`docs/adding_a_skill.md`](docs/adding_a_skill.md) | How to add a new `vla.*` or `locomotion.*` skill |
