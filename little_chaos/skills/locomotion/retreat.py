from __future__ import annotations

import math

from little_chaos.backends.sonic.client import SonicClient
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult, SkillStatus
from little_chaos.skills.locomotion.base import LocomotionExecutor
from little_chaos.world.observation import WorldState


def _dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = float(a[0]) - float(b[0])
    dy = float(a[1]) - float(b[1])
    return dx * dx + dy * dy


class RetreatExecutor(LocomotionExecutor):
    """Closed-loop locomotion: retreat until traveled distance >= target."""

    def __init__(
        self,
        *,
        world: WorldState,
        sonic: SonicClient,
        timeout_s: float,
        retreat_distance_min_m: float,
        retreat_distance_max_m: float,
    ) -> None:
        super().__init__(world=world, sonic=sonic, timeout_s=timeout_s)
        self._distance_m: float = 0.5
        self._start_xy: tuple[float, float] | None = None
        self._yaw_at_start: float | None = None
        self._min = float(retreat_distance_min_m)
        self._max = float(retreat_distance_max_m)

    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        await super().start(call, ctx)
        distance_m = float(call.arguments.get("distance_m"))
        if not (self._min <= distance_m <= self._max):
            raise ValueError(f"distance_m {distance_m} out of range")
        self._distance_m = distance_m

        snap = self._world.snapshot()
        if snap.robot_xy is None:
            self._start_xy = (0.0, 0.0)
        else:
            self._start_xy = (float(snap.robot_xy[0]), float(snap.robot_xy[1]))
        self._yaw_at_start = float(snap.yaw or 0.0)

        current_yaw = float(self._world.snapshot().yaw or self._yaw_at_start or 0.0)
        await self._sonic.retreat(yaw=current_yaw)

    async def poll(self, ctx: TaskContext) -> SkillResult:
        if self._cancelled:
            return SkillResult(status=SkillStatus.CANCELLED, reason="cancelled")
        if self._started_at is None or self._start_xy is None:
            return SkillResult(status=SkillStatus.FAILURE, reason="not started")

        if self._elapsed() > self._timeout_s:
            await self._sonic.stop(yaw=self._world.snapshot().yaw)
            return SkillResult(status=SkillStatus.FAILURE, reason="timeout")

        safety = self._safety_check()
        if safety is not None:
            await self._sonic.stop(yaw=self._world.snapshot().yaw)
            return safety

        snap = self._world.snapshot()
        if snap.robot_xy is None:
            return SkillResult(status=SkillStatus.FAILURE, reason="no robot pose")
        current_xy = (float(snap.robot_xy[0]), float(snap.robot_xy[1]))
        dist_m = math.sqrt(_dist2(self._start_xy, current_xy))

        if dist_m >= self._distance_m:
            await self._sonic.stop(yaw=float(snap.yaw or 0.0))
            return SkillResult(status=SkillStatus.SUCCESS, reason="retreat distance complete")

        yaw = float(snap.yaw or self._yaw_at_start or 0.0)
        await self._sonic.retreat(yaw=yaw)
        return SkillResult(status=SkillStatus.RUNNING, reason=f"retreat dist {dist_m:.2f}m")

