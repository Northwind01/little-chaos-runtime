from __future__ import annotations

from little_chaos.backends.sonic.client import SonicClient
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult, SkillStatus
from little_chaos.skills.locomotion.base import LocomotionExecutor
from little_chaos.world.observation import WorldState


class StopExecutor(LocomotionExecutor):
    """Immediately send SONIC IDLE / zero-motion."""

    def __init__(self, *, world: WorldState, sonic: SonicClient, timeout_s: float) -> None:
        super().__init__(world=world, sonic=sonic, timeout_s=timeout_s)

    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        await super().start(call, ctx)
        snap = self._world.snapshot()
        await self._sonic.stop(yaw=snap.yaw)

    async def poll(self, ctx: TaskContext) -> SkillResult:
        if self._cancelled:
            return SkillResult(status=SkillStatus.CANCELLED, reason="cancelled")
        safety = self._safety_check()
        if safety is not None:
            return safety
        return SkillResult(status=SkillStatus.SUCCESS, reason="stopped")

