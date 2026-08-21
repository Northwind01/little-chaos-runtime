from __future__ import annotations

from abc import ABC, abstractmethod

from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import Observation, SkillCall, SkillResult, SkillSpec


class SuccessDetector(ABC):
    """Semantic success only. Must never send robot commands."""

    @abstractmethod
    async def evaluate(
        self,
        spec: SkillSpec,
        call: SkillCall,
        observation: Observation,
        ctx: TaskContext,
    ) -> SkillResult:
        ...
