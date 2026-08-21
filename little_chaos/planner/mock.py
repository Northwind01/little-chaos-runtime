"""Deterministic planner for infrastructure tests. Not the production planner."""

from __future__ import annotations

import re
from typing import Any

from little_chaos.planner.base import PlannerBackend, PlannerDecision
from little_chaos.runtime.types import (
    Observation,
    PlannerDecisionType,
    SkillCall,
)
from little_chaos.skills.registry import SkillRegistry

_COMPLETE = PlannerDecision(
    type=PlannerDecisionType.TASK_COMPLETE,
    reason="mock planner finished registered sequence",
)


def _norm(text: str) -> str:
    lowered = text.strip().lower()
    lowered = lowered.replace("'", "")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _seq(*calls: SkillCall) -> list[PlannerDecision]:
    return [
        PlannerDecision(type=PlannerDecisionType.SKILL, skill=call)
        for call in calls
    ] + [_COMPLETE]


_FIND_AND_GO = _seq(
    SkillCall("vla.find_girl", {}),
    SkillCall("vla.go_to_girl", {}),
)

SEQUENCES: dict[str, list[PlannerDecision]] = {
    # Short prompts people type in the shell
    "find the girl": _FIND_AND_GO,
    "find girl": _FIND_AND_GO,
    "find the girl.": _FIND_AND_GO,
    "find the girl and go to her": _FIND_AND_GO,
    "find girl and go to her": _FIND_AND_GO,
    "go to the girl": _seq(SkillCall("vla.go_to_girl", {})),
    "turn around and walk away": _seq(
        SkillCall("locomotion.turn_around", {}),
        SkillCall("locomotion.walk", {"direction": "forward", "speed": "slow", "duration_s": 1.0}),
    ),
    "find the girl approach her retreat then stop": _seq(
        SkillCall("vla.find_girl", {}),
        SkillCall("vla.go_to_girl", {}),
        SkillCall("locomotion.retreat", {"distance_m": 0.5}),
        SkillCall("locomotion.stop", {}),
    ),
    "find the girl go to her turn around retreat half a meter stop": _seq(
        SkillCall("vla.find_girl", {}),
        SkillCall("vla.go_to_girl", {}),
        SkillCall("locomotion.turn_around", {}),
        SkillCall("locomotion.retreat", {"distance_m": 0.5}),
        SkillCall("locomotion.stop", {}),
    ),
}


class MockPlanner(PlannerBackend):
    def __init__(self, sequences: dict[str, list[PlannerDecision]] | None = None) -> None:
        self._sequences = {_norm(k): list(v) for k, v in (sequences or SEQUENCES).items()}
        self._index: dict[str, int] = {}

    async def next_skill(
        self,
        task: str,
        observation: Observation,
        history: list[dict[str, Any]],
        skills: SkillRegistry,
    ) -> PlannerDecision:
        key = _norm(task)
        sequence = self._sequences.get(key)
        if sequence is None:
            return PlannerDecision(
                type=PlannerDecisionType.CANNOT_COMPLETE,
                reason=f"mock planner has no sequence for {task!r}",
            )
        idx = self._index.get(key, 0)
        if idx >= len(sequence):
            return _COMPLETE
        decision = sequence[idx]
        self._index[key] = idx + 1
        if decision.type is PlannerDecisionType.SKILL and decision.skill is not None:
            decision = PlannerDecision(
                type=decision.type,
                skill=skills.validate_call(decision.skill),
                reason=decision.reason,
                raw=decision.raw,
            )
        return decision

    def reset(self) -> None:
        self._index.clear()
