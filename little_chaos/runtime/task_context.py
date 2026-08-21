"""Mutable per-task execution context owned by the runtime."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from little_chaos.runtime.types import (
    HistoryEvent,
    PrivilegedSnapshot,
    SkillCall,
    SkillResult,
    SkillStatus,
)


@dataclass
class TaskContext:
    task_id: str = ""
    user_command: str = ""
    started_at: float | None = None
    skill_started_at: float | None = None
    active_skill: SkillCall | None = None
    last_result: SkillResult | None = None
    last_detector: SkillResult | None = None
    last_privileged: PrivilegedSnapshot | None = None
    history: list[HistoryEvent] = field(default_factory=list)
    skill_count: int = 0
    cancelled: bool = False
    stop_requested: bool = False

    def begin_task(self, user_command: str) -> None:
        self.task_id = uuid.uuid4().hex[:12]
        self.user_command = user_command
        self.started_at = time.monotonic()
        self.skill_started_at = None
        self.active_skill = None
        self.last_result = None
        self.last_detector = None
        self.last_privileged = None
        self.history = []
        self.skill_count = 0
        self.cancelled = False
        self.stop_requested = False
        self.record("task", {"command": user_command, "task_id": self.task_id})

    def begin_skill(self, call: SkillCall) -> None:
        self.active_skill = call
        self.skill_started_at = time.monotonic()
        self.skill_count += 1
        self.last_detector = None
        self.record(
            "skill_start",
            {"skill": call.name, "arguments": dict(call.arguments)},
        )

    def end_skill(self, result: SkillResult) -> None:
        self.last_result = result
        payload: dict[str, Any] = {
            "skill": self.active_skill.name if self.active_skill else None,
            "status": result.status.value,
            "reason": result.reason,
            "confidence": result.confidence,
        }
        self.record("skill_end", payload)
        self.active_skill = None
        self.skill_started_at = None

    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self.started_at)

    def skill_elapsed_s(self) -> float:
        if self.skill_started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self.skill_started_at)

    def record(self, kind: str, payload: dict[str, Any] | None = None) -> HistoryEvent:
        event = HistoryEvent(kind=kind, payload=dict(payload or {}))
        self.history.append(event)
        return event

    def history_for_planner(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for event in self.history:
            if event.kind in {"skill_start", "skill_end", "verify", "plan", "task"}:
                row = {"kind": event.kind, **event.payload}
                out.append(row)
        return out[-24:]

    def mark_cancelled(self, reason: str = "manual stop") -> SkillResult:
        self.cancelled = True
        self.stop_requested = True
        result = SkillResult(status=SkillStatus.CANCELLED, reason=reason)
        if self.active_skill is not None:
            self.end_skill(result)
        else:
            self.last_result = result
            self.record("cancelled", {"reason": reason})
        return result
