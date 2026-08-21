"""Skill executor protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod

from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult


class SkillExecutor(ABC):
    @abstractmethod
    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        ...

    @abstractmethod
    async def poll(self, ctx: TaskContext) -> SkillResult:
        ...

    @abstractmethod
    async def cancel(self) -> None:
        ...
