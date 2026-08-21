"""Validated skill registry. Planner output is checked here before execution."""

from __future__ import annotations

from typing import Any, Iterable

from little_chaos.runtime.types import RuntimeConfig, SkillCall, SkillSpec
from little_chaos.skills.base import SkillExecutor


class SkillRegistryError(ValueError):
    pass


class SkillRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, SkillSpec] = {}
        self._executors: dict[str, SkillExecutor] = {}

    def register(self, spec: SkillSpec, executor: SkillExecutor) -> None:
        if spec.name in self._specs:
            raise SkillRegistryError(f"duplicate skill {spec.name!r}")
        self._specs[spec.name] = spec
        self._executors[spec.name] = executor

    def get(self, name: str) -> SkillSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise SkillRegistryError(f"unsupported skill {name!r}") from exc

    def executor(self, name: str) -> SkillExecutor:
        spec = self.get(name)
        return self._executors[spec.name]

    def names(self) -> list[str]:
        return sorted(self._specs)

    def specs(self) -> list[SkillSpec]:
        return [self._specs[name] for name in self.names()]

    def planner_catalog(self) -> list[dict[str, Any]]:
        catalog = []
        for spec in self.specs():
            catalog.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "executor_type": spec.executor_type,
                    "timeout_s": spec.timeout_s,
                    "arguments": spec.argument_schema,
                    "canonical_instruction": spec.canonical_instruction,
                }
            )
        return catalog

    def validate_call(self, call: SkillCall) -> SkillCall:
        if not isinstance(call.name, str) or not call.name:
            raise SkillRegistryError("skill name must be a non-empty string")
        spec = self.get(call.name)
        args = dict(call.arguments or {})
        cleaned = validate_arguments(spec, args)
        return SkillCall(name=spec.name, arguments=cleaned)


def validate_arguments(spec: SkillSpec, arguments: dict[str, Any]) -> dict[str, Any]:
    schema = spec.argument_schema or {}
    extra = set(arguments) - set(schema)
    if extra:
        raise SkillRegistryError(
            f"skill {spec.name!r} got unsupported arguments: {sorted(extra)}"
        )
    cleaned: dict[str, Any] = {}
    for name, field in schema.items():
        required = bool(field.get("required", False))
        if name not in arguments:
            if required:
                raise SkillRegistryError(f"skill {spec.name!r} missing argument {name!r}")
            if "default" in field:
                cleaned[name] = field["default"]
            continue
        cleaned[name] = _coerce_field(spec.name, name, arguments[name], field)
    return cleaned


def _coerce_field(skill: str, name: str, value: Any, field: dict[str, Any]) -> Any:
    kind = field.get("type", "any")
    if kind == "string":
        if not isinstance(value, str):
            raise SkillRegistryError(f"{skill}.{name} must be a string")
        allowed = field.get("enum")
        if allowed is not None and value not in allowed:
            raise SkillRegistryError(
                f"{skill}.{name} must be one of {list(allowed)}, got {value!r}"
            )
        return value
    if kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise SkillRegistryError(f"{skill}.{name} must be a number") from exc
        lo = field.get("min")
        hi = field.get("max")
        if lo is not None and number < float(lo):
            raise SkillRegistryError(f"{skill}.{name}={number} below min {lo}")
        if hi is not None and number > float(hi):
            raise SkillRegistryError(f"{skill}.{name}={number} above max {hi}")
        return number
    return value


def default_skill_specs(config: RuntimeConfig | None = None) -> list[SkillSpec]:
    cfg = config or RuntimeConfig()
    return [
        SkillSpec(
            name="vla.find_girl",
            description=(
                "Search for and visually locate the girl using the fine-tuned GR00T policy."
            ),
            executor_type="vla",
            timeout_s=cfg.vla_timeout_s,
            interruptible=True,
            canonical_instruction="Find the girl",
            success_detector="vlm",
            argument_schema={},
        ),
        SkillSpec(
            name="vla.go_to_girl",
            description="Approach the girl using the fine-tuned GR00T policy.",
            executor_type="vla",
            timeout_s=cfg.vla_timeout_s,
            interruptible=True,
            canonical_instruction="Go to the girl",
            success_detector="vlm",
            argument_schema={},
        ),
        SkillSpec(
            name="locomotion.walk",
            description="Walk a short bounded distance in a cardinal world direction.",
            executor_type="locomotion",
            timeout_s=cfg.walk_max_duration_s + 1.0,
            interruptible=True,
            argument_schema={
                "direction": {
                    "type": "string",
                    "enum": ["forward", "backward", "left", "right"],
                    "default": "forward",
                },
                "speed": {
                    "type": "string",
                    "enum": ["slow", "normal"],
                    "default": "slow",
                },
                "duration_s": {
                    "type": "number",
                    "min": 0.1,
                    "max": cfg.walk_max_duration_s,
                    "default": 1.0,
                },
            },
        ),
        SkillSpec(
            name="locomotion.stop",
            description="Immediately send SONIC IDLE / zero-motion and halt.",
            executor_type="locomotion",
            timeout_s=2.0,
            interruptible=True,
            argument_schema={},
        ),
        SkillSpec(
            name="locomotion.retreat",
            description="Walk backward a requested distance, then stop.",
            executor_type="locomotion",
            timeout_s=20.0,
            interruptible=True,
            argument_schema={
                "distance_m": {
                    "type": "number",
                    "min": cfg.retreat_min_m,
                    "max": cfg.retreat_max_m,
                    "required": True,
                },
            },
        ),
        SkillSpec(
            name="locomotion.turn_around",
            description="Rotate in place until yaw has changed by approximately 180 degrees.",
            executor_type="locomotion",
            timeout_s=cfg.turn_timeout_s,
            interruptible=True,
            argument_schema={},
        ),
    ]


def build_default_registry(
    executors: dict[str, SkillExecutor],
    config: RuntimeConfig | None = None,
) -> SkillRegistry:
    registry = SkillRegistry()
    for spec in default_skill_specs(config):
        if spec.name not in executors:
            raise SkillRegistryError(f"no executor provided for {spec.name}")
        registry.register(spec, executors[spec.name])
    missing = set(executors) - set(registry.names())
    if missing:
        raise SkillRegistryError(f"executors for unknown skills: {sorted(missing)}")
    return registry


def specs_by_name(specs: Iterable[SkillSpec]) -> dict[str, SkillSpec]:
    return {spec.name: spec for spec in specs}
