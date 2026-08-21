from __future__ import annotations

import time

from little_chaos.backends.sonic.client import SonicClient
from little_chaos.backends.sonic.locomotion import turn_around_target, yaw_error
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult, SkillStatus
from little_chaos.skills.locomotion.base import LocomotionExecutor
from little_chaos.world.observation import WorldState


class TurnAroundExecutor(LocomotionExecutor):
    """Closed-loop controller using MuJoCo yaw feedback."""

    def __init__(
        self,
        *,
        world: WorldState,
        sonic: SonicClient,
        timeout_s: float,
        yaw_tolerance_rad: float,
    ) -> None:
        super().__init__(world=world, sonic=sonic, timeout_s=timeout_s)
        self._yaw_tolerance_rad = float(yaw_tolerance_rad)
        self._initial_yaw: float | None = None
        self._target_yaw: float | None = None

    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        await super().start(call, ctx)
        self._initial_yaw = float(self._world.snapshot().yaw or 0.0)
        self._target_yaw = turn_around_target(self._initial_yaw)

        # Kick the controller.
        await self._sonic.turn_around(target_yaw=self._target_yaw)

    async def poll(self, ctx: TaskContext) -> SkillResult:
        if self._cancelled:
            return SkillResult(status=SkillStatus.CANCELLED, reason="cancelled")
        if self._started_at is None or self._target_yaw is None:
            return SkillResult(status=SkillStatus.FAILURE, reason="not started")

        if self._elapsed() > self._timeout_s:
            await self._sonic.stop(yaw=self._world.snapshot().yaw)
            return SkillResult(status=SkillStatus.FAILURE, reason="timeout")

        safety = self._safety_check()
        if safety is not None:
            await self._sonic.stop(yaw=self._world.snapshot().yaw)
            return safety

        current_yaw = float(self._world.snapshot().yaw or 0.0)
        err = abs(yaw_error(current=current_yaw, target=self._target_yaw))
        if err <= self._yaw_tolerance_rad:
            await self._sonic.stop(yaw=current_yaw)
            return SkillResult(status=SkillStatus.SUCCESS, reason="turned around")

        await self._sonic.turn_around(target_yaw=self._target_yaw)
        return SkillResult(status=SkillStatus.RUNNING, reason=f"yaw error {err:.3f}")

