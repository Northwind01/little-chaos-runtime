from __future__ import annotations

import time

from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult, SkillStatus
from little_chaos.runtime.types import RuntimeConfig
from little_chaos.runtime.types import PrivilegedSnapshot
from little_chaos.runtime.ownership import ControlOwnershipError
from little_chaos.skills.base import SkillExecutor
from little_chaos.world.observation import WorldState
from little_chaos.backends.sonic.client import SonicClient


def _veto_to_failure(veto: str) -> SkillResult:
    return SkillResult(
        status=SkillStatus.FAILURE,
        reason=veto,
        metadata={},
    )


class LocomotionExecutor(SkillExecutor):
    """Locomotion skills use world feedback to decide when to stop.

    They reuse the existing observational collision supervision via
    `world.safety_veto()`.
    """

    def __init__(self, *, world: WorldState, sonic: SonicClient, timeout_s: float) -> None:
        self._world = world
        self._sonic = sonic
        self._timeout_s = float(timeout_s)
        self._started_at: float | None = None
        self._cancelled = False

    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        self._cancelled = False
        self._started_at = time.monotonic()

    def _elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def _safety_check(self) -> SkillResult | None:
        veto = None
        try:
            veto = self._world.safety_veto()
        except Exception as exc:
            return SkillResult(status=SkillStatus.FAILURE, reason=f"safety check error: {exc}")

        if veto:
            return _veto_to_failure(veto)
        return None

    async def cancel(self) -> None:
        self._cancelled = True
        # We rely on the runtime's STOP_SKILL stage to send an idle command.
        # Cancel here only flips flags.

    async def poll(self, ctx: TaskContext) -> SkillResult:
        if self._cancelled:
            return SkillResult(status=SkillStatus.CANCELLED, reason="cancelled")

        if self._started_at is None:
            return SkillResult(status=SkillStatus.FAILURE, reason="not started")

        if self._elapsed() > self._timeout_s:
            return SkillResult(status=SkillStatus.FAILURE, reason="timeout")

        safety = self._safety_check()
        if safety is not None:
            return safety

        raise NotImplementedError

