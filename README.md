# little-chaos-runtime

High-level LittleChaos execution runtime above the existing GR00T + SONIC stack.

Full runbook (how to run, shell commands, allowed tasks, skills, failures):
[`docs/execution_runtime.md`](docs/execution_runtime.md).

## Quick start

**Offline / demo** (mock planner, no sim):

```bash
make shell
```

**Live autonomous** (tmux: sim + controller + policy + runtime + connect-mode inference):

```bash
make live MODEL=/checkpoints/<your_ckpt> PROMPT='Find the girl.' SCENARIO=little_chaos
```

Tear down: `make live-down`

`make help` lists targets. Full runbook: [`docs/execution_runtime.md`](docs/execution_runtime.md).

In the **runtime** pane:

| Input | Meaning |
| --- | --- |
| `:help` | Shell commands |
| `:tasks` | Allowed mock-planner phrases |
| `:skills` | Registered skills |
| `:status` / `:stop` / `:quit` | Status, cancel episode, exit |
| `find the girl` | Example task (mock → find then go-to) |

Anything that is not a `:command` is a task string. With the default mock planner, unknown phrases return `cannot_complete` — use `:tasks`.
