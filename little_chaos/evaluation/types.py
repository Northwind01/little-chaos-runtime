"""Evaluation result types. Detectors never command the robot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from little_chaos.runtime.types import PrivilegedSnapshot, SkillResult, SkillStatus

DETECTOR_STATUSES = frozenset(
    {
        SkillStatus.RUNNING,
        SkillStatus.SUCCESS,
        SkillStatus.FAILURE,
        SkillStatus.UNCERTAIN,
    }
)


class DetectorSchemaError(ValueError):
    pass


def parse_detector_payload(payload: dict[str, Any]) -> SkillResult:
    if not isinstance(payload, dict):
        raise DetectorSchemaError("detector output must be an object")
    raw = payload.get("status") or payload.get("state")
    if not isinstance(raw, str):
        raise DetectorSchemaError("detector status is required")
    try:
        status = SkillStatus(raw.strip().lower())
    except ValueError as exc:
        raise DetectorSchemaError(f"invalid detector status {raw!r}") from exc
    if status not in DETECTOR_STATUSES:
        raise DetectorSchemaError(f"detector cannot return {status.value}")
    confidence = payload.get("confidence")
    if confidence is not None:
        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise DetectorSchemaError("confidence must be in [0, 1]")
    return SkillResult(
        status=status,
        reason=payload.get("reason"),
        confidence=confidence,
        metadata=dict(payload.get("metadata") or {}),
    )


@dataclass
class GroundTruthReport:
    snapshot: PrivilegedSnapshot = field(default_factory=PrivilegedSnapshot)
    notes: dict[str, Any] = field(default_factory=dict)
