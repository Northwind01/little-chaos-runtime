# Adding a skill

A skill is a named, validated action the planner may request. Wiring has three parts that must stay in sync:

1. **`SkillSpec`** — name, description, args schema, timeout, detector
2. **`SkillExecutor`** — `start` / `poll` / `cancel`
3. **Factory registration** — construct the executor and pass it into the registry

Optional: mock-planner phrase, VLA canonical prompt map, tests.

Name skills as `family.action` (e.g. `vla.find_girl`, `locomotion.walk`). The orchestrator maps:

- `vla.*` → command source `GROOT`
- `locomotion.*` → command source `LOCOMOTION`
- anything else → `NONE` (no robot command ownership)

---

## Checklist

1. Implement an executor under `little_chaos/skills/<family>/`.
2. Export it from that package’s `__init__.py`.
3. Add a `SkillSpec` in `default_skill_specs()` (`little_chaos/skills/registry.py`).
4. Instantiate it in `_attach_executors()` (`little_chaos/cli/factory.py`).
5. If VLA: add the canonical GR00T string in `GrootVlaExecutor._canonical_instruction`.
6. If you want offline `make shell` demos: add a phrase in `little_chaos/planner/mock.py` `SEQUENCES`.
7. Add/extend a unit test (args validation and/or executor poll behavior).
8. Run `make test`. Confirm `:skills` lists the new name.

`build_default_registry` requires **exact** overlap between specs and executors — a missing or extra key fails at startup.

---

## 1. Executor contract

```python
class SkillExecutor(ABC):
    async def start(self, call: SkillCall, ctx: TaskContext) -> None: ...
    async def poll(self, ctx: TaskContext) -> SkillResult: ...
    async def cancel(self) -> None: ...
```

`poll` returns `SkillResult` with status:

| Status | Meaning |
| --- | --- |
| `RUNNING` | Keep ticking |
| `SUCCESS` / `FAILURE` / `CANCELLED` | Terminal — orchestrator stops the skill |

**VLA skills** should usually keep returning `RUNNING` until timeout; semantic success comes from `SuccessDetector` when `SkillSpec.success_detector` is set (e.g. `"vlm"`). Do **not** send locomotion commands from a VLA executor.

**Locomotion skills** may declare their own success (duration done, yaw reached, …) and must honor `world.safety_veto()` (collision / fallen).

Reuse bases when possible:

- `little_chaos/skills/vla/base.py` — `GrootVlaExecutor`
- `little_chaos/skills/locomotion/base.py` — `LocomotionExecutor`

---

## 2. Example: new VLA skill

Goal: `vla.wave` with canonical prompt `"Wave hello"`.

### Executor

`little_chaos/skills/vla/wave.py`:

```python
from little_chaos.skills.vla.base import GrootVlaExecutor


class VlaWaveExecutor(GrootVlaExecutor):
    """Executor for `vla.wave`."""

    pass
```

Export from `little_chaos/skills/vla/__init__.py`.

### Canonical prompt

In `GrootVlaExecutor._canonical_instruction`, extend the map:

```python
mapping = {
    "vla.find_girl": "Find the girl",
    "vla.go_to_girl": "Go to the girl",
    "vla.wave": "Wave hello",
}
```

Prompts must stay fixed strings — do not pass planner free text into GR00T.

### Spec

In `default_skill_specs()`:

```python
SkillSpec(
    name="vla.wave",
    description="Wave hello using the fine-tuned GR00T policy.",
    executor_type="vla",
    timeout_s=cfg.vla_timeout_s,
    interruptible=True,
    canonical_instruction="Wave hello",
    success_detector="vlm",
    argument_schema={},
),
```

### Factory

In `_attach_executors()`:

```python
"vla.wave": VlaWaveExecutor(groot=groot, timeout_s=config.vla_timeout_s),
```

(Import `VlaWaveExecutor` at the top of `factory.py`.)

---

## 3. Example: new locomotion skill

Goal: `locomotion.sidestep` with required `side` enum.

### Executor sketch

```python
class SidestepExecutor(LocomotionExecutor):
    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        await super().start(call, ctx)
        side = str(call.arguments["side"]).lower()
        yaw = self._world.snapshot().yaw or 0.0
        # Map side → SonicClient / planner packets…
        await self._sonic.walk(
            direction="left" if side == "left" else "right",
            speed="slow",
            yaw=yaw,
        )

    async def poll(self, ctx: TaskContext) -> SkillResult:
        if self._cancelled:
            return SkillResult(status=SkillStatus.CANCELLED, reason="cancelled")
        safety = self._safety_check()
        if safety is not None:
            await self._sonic.stop(yaw=self._world.snapshot().yaw)
            return safety
        if self._elapsed() > self._timeout_s:
            await self._sonic.stop(yaw=self._world.snapshot().yaw)
            return SkillResult(status=SkillStatus.FAILURE, reason="timeout")
        # …success condition…
        return SkillResult(status=SkillStatus.RUNNING)
```

Prefer extending `SonicClient` / `locomotion.py` helpers for new packet shapes instead of packing ZMQ in the skill.

### Spec with arguments

```python
SkillSpec(
    name="locomotion.sidestep",
    description="Take a short lateral step.",
    executor_type="locomotion",
    timeout_s=5.0,
    interruptible=True,
    argument_schema={
        "side": {
            "type": "string",
            "enum": ["left", "right"],
            "required": True,
        },
    },
),
```

Supported schema fields today (`validate_arguments`):

- `type`: `"string"` | `"number"` | omit / `"any"`
- `enum`: list (strings)
- `min` / `max`: for numbers
- `required`: bool
- `default`: used when the arg is omitted

Unknown argument keys are rejected.

---

## 4. Mock planner phrases (optional)

Default `PLANNER_BACKEND=mock` only runs fixed phrases. To exercise the skill offline:

```python
# little_chaos/planner/mock.py
"wave hello": _seq(SkillCall("vla.wave", {})),
"sidestep left": _seq(SkillCall("locomotion.sidestep", {"side": "left"})),
```

Matching is normalized (case / punctuation). List live with `:tasks`.

For open-ended language, use `PLANNER_BACKEND=vesta` — the planner still must emit a validated skill name + args from the registry catalog.

---

## 5. Tests

Minimal coverage:

- Spec appears in `default_skill_specs` / `:skills`
- Invalid args raise `SkillRegistryError` (see `tests/test_skill_registry.py`)
- Executor `poll` returns expected terminal status under a fake world / clients

```bash
make test
```

---

## Rules of thumb

- Keep skills small and composable; put multi-step logic in the planner.
- Do not import SONIC internals from planner code; skills talk through `SonicClient` / `GrootClient`.
- Detectors must never send robot commands.
- Prefer thin adapters over copying GR00T/SONIC protocol into the skill file.
- After adding a skill, update the skills table in [`execution_runtime.md`](execution_runtime.md) if it is user-facing.
