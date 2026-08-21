import pytest

from little_chaos.planner.base import parse_planner_payload, PlannerParseError
from little_chaos.planner.mock import SEQUENCES
from little_chaos.runtime.types import RuntimeConfig
from little_chaos.skills.registry import SkillRegistry, default_skill_specs
from little_chaos.skills.base import SkillExecutor
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult, SkillStatus


class DummyExecutor(SkillExecutor):
    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        return

    async def poll(self, ctx: TaskContext) -> SkillResult:
        return SkillResult(status=SkillStatus.RUNNING)

    async def cancel(self) -> None:
        return


def _registry() -> SkillRegistry:
    cfg = RuntimeConfig()
    reg = SkillRegistry()
    for spec in default_skill_specs(cfg):
        reg.register(spec=spec, executor=DummyExecutor())
    return reg


def test_parse_skill_decision_validates_arguments() -> None:
    reg = _registry()
    payload = {
        "type": "skill",
        "skill": "locomotion.walk",
        "arguments": {"direction": "forward", "speed": "normal", "duration_s": 0.5},
    }
    decision = parse_planner_payload(payload, reg)
    assert decision.type.value == "skill"
    assert decision.skill.name == "locomotion.walk"
    assert decision.skill.arguments["speed"] == "normal"


def test_parse_skill_decision_rejects_unknown_skill() -> None:
    reg = _registry()
    payload = {"type": "skill", "skill": "nope.unknown", "arguments": {}}
    with pytest.raises(PlannerParseError):
        parse_planner_payload(payload, reg)


def test_parse_task_complete() -> None:
    reg = _registry()
    payload = {"type": "task_complete", "reason": "all done"}
    decision = parse_planner_payload(payload, reg)
    assert decision.type.value == "task_complete"
    assert "all done" in (decision.reason or "")

