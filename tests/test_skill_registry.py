import pytest

from little_chaos.runtime.types import RuntimeConfig
from little_chaos.skills.registry import SkillRegistry, SkillRegistryError, default_skill_specs
from little_chaos.runtime.types import SkillCall
from little_chaos.skills.base import SkillExecutor
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillResult, SkillStatus, SkillSpec


class DummyExecutor(SkillExecutor):
    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        return

    async def poll(self, ctx: TaskContext) -> SkillResult:
        return SkillResult(status=SkillStatus.RUNNING)

    async def cancel(self) -> None:
        return


def _registry_for(skill_name: str) -> SkillRegistry:
    cfg = RuntimeConfig()
    spec = next(s for s in default_skill_specs(cfg) if s.name == skill_name)
    reg = SkillRegistry()
    reg.register(spec=spec, executor=DummyExecutor())
    return reg


def test_walk_defaults_are_applied() -> None:
    reg = _registry_for("locomotion.walk")
    call = reg.validate_call(SkillCall(name="locomotion.walk", arguments={}))
    assert call.arguments["direction"] == "forward"
    assert call.arguments["speed"] == "slow"
    assert call.arguments["duration_s"] == pytest.approx(1.0)


def test_walk_rejects_invalid_enum() -> None:
    reg = _registry_for("locomotion.walk")
    with pytest.raises(SkillRegistryError):
        reg.validate_call(SkillCall(name="locomotion.walk", arguments={"direction": "up"}))


def test_retreat_requires_distance_m() -> None:
    reg = _registry_for("locomotion.retreat")
    with pytest.raises(SkillRegistryError):
        reg.validate_call(SkillCall(name="locomotion.retreat", arguments={}))


def test_retreat_rejects_extra_arg() -> None:
    reg = _registry_for("locomotion.retreat")
    with pytest.raises(SkillRegistryError):
        reg.validate_call(SkillCall(name="locomotion.retreat", arguments={"distance_m": 0.5, "foo": 1}))

