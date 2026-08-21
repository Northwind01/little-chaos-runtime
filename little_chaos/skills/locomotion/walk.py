from __future__ import annotations

import math
import time

from little_chaos.backends.sonic.locomotion import WALK_DIRECTIONS, WALK_SPEEDS
from little_chaos.backends.sonic.client import SonicClient
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult, SkillStatus
from little_chaos.world.observation import WorldState
from little_chaos.skills.locomotion.base import LocomotionExecutor
from little_chaos.backends.sonic.locomotion import yaw_error


class WalkExecutor(LocomotionExecutor):
    """Bounded planner-facing `locomotion.walk` skill.

    Bounded by `duration_s` (planner argument), and additionally aborts on
    safety veto (collision / robot fallen).
    """

    def __init__(
        self,
        *,
        world: WorldState,
        sonic: SonicClient,
        timeout_s: float,
    ) -> None:
        super().__init__(world=world, sonic=sonic, timeout_s=timeout_s)
        self._duration_s: float = 1.0
        self._direction: str = "forward"
        self._speed: str = "slow"
        self._started_yaw: float | None = None

    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        await super().start(call, ctx)
        self._duration_s = float(call.arguments.get("duration_s", 1.0))
        self._direction = str(call.arguments.get("direction", "forward")).lower()
        self._speed = str(call.arguments.get("speed", "slow")).lower()
        self._started_yaw = self._world.snapshot().yaw or 0.0
        await self._sonic.walk(direction=self._direction, speed=self._speed, yaw=self._started_yaw)

    async def poll(self, ctx: TaskContext) -> SkillResult:
        # Safety/timeout/cancel are shared.
        if self._cancelled:
            return SkillResult(status=SkillStatus.CANCELLED, reason="cancelled")
        if self._started_at is None:
            return SkillResult(status=SkillStatus.FAILURE, reason="not started")

        if self._elapsed() > self._timeout_s:
            return SkillResult(status=SkillStatus.FAILURE, reason="timeout")

        safety = self._safety_check()
        if safety is not None:
            await self._sonic.stop(yaw=self._world.snapshot().yaw)
            return safety

        # Continue sending bounded walk commands so SONIC keeps moving.
        yaw = self._world.snapshot().yaw or (self._started_yaw or 0.0)
        if self._elapsed() <= self._duration_s:
            await self._sonic.walk(direction=self._direction, speed=self._speed, yaw=yaw)
            return SkillResult(status=SkillStatus.RUNNING)

        await self._sonic.stop(yaw=yaw)
        return SkillResult(status=SkillStatus.SUCCESS, reason="walk duration complete")

