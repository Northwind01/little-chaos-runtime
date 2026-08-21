from __future__ import annotations

import time

from little_chaos.backends.groot.client import GrootClient
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import SkillCall, SkillResult, SkillStatus
from little_chaos.skills.base import SkillExecutor


class GrootVlaExecutor(SkillExecutor):
    """Thin wrapper: starts/stops the GR00T VLA process, then relies on
    `SuccessDetector` (VLM/ground-truth) for semantic completion.

    This executor must never decide success by itself and must never issue
    any robot locomotion commands.
    """

    def __init__(
        self,
        *,
        groot: GrootClient,
        timeout_s: float,
    ) -> None:
        self._groot = groot
        self._timeout_s = float(timeout_s)
        self._started_at: float | None = None
        self._cancelled = False

    @staticmethod
    def _canonical_instruction(skill_name: str) -> str:
        # Keep these canonical strings stable so planner cannot inject arbitrary text.
        mapping = {
            "vla.find_girl": "Find the girl",
            "vla.go_to_girl": "Go to the girl",
        }
        return mapping.get(skill_name, skill_name)

    async def start(self, call: SkillCall, ctx: TaskContext) -> None:
        self._cancelled = False
        self._started_at = time.monotonic()
        await self._groot.start_skill(instruction=self._canonical_instruction(call.name))

    async def poll(self, ctx: TaskContext) -> SkillResult:
        if self._cancelled:
            return SkillResult(status=SkillStatus.CANCELLED, reason="cancelled")
        if self._started_at is None:
            return SkillResult(status=SkillStatus.FAILURE, reason="not started")
        elapsed = time.monotonic() - self._started_at
        if elapsed > self._timeout_s:
            return SkillResult(status=SkillStatus.FAILURE, reason="timeout")
        # Completion is determined by SuccessDetector, not by this executor.
        return SkillResult(status=SkillStatus.RUNNING)

    async def cancel(self) -> None:
        self._cancelled = True
        await self._groot.cancel()

