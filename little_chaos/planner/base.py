"""Planner backend protocol and JSON decision parsing."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from little_chaos.runtime.types import (
    Observation,
    PlannerDecision,
    PlannerDecisionType,
    SkillCall,
)
from little_chaos.skills.registry import SkillRegistry, SkillRegistryError


class PlannerBackend(ABC):
    @abstractmethod
    async def next_skill(
        self,
        task: str,
        observation: Observation,
        history: list[dict[str, Any]],
        skills: SkillRegistry,
    ) -> PlannerDecision:
        ...


class PlannerParseError(ValueError):
    pass


def parse_planner_payload(payload: Any, registry: SkillRegistry) -> PlannerDecision:
    data = _as_dict(payload)
    kind = str(data.get("type") or "").strip().lower()
    if kind in {"skill", "action"}:
        name = data.get("skill") or data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PlannerParseError("skill decision is missing skill name")
        arguments = data.get("arguments") or data.get("args") or {}
        if not isinstance(arguments, dict):
            raise PlannerParseError("skill arguments must be an object")
        call = SkillCall(name=name.strip(), arguments=dict(arguments))
        try:
            call = registry.validate_call(call)
        except SkillRegistryError as exc:
            raise PlannerParseError(str(exc)) from exc
        return PlannerDecision(
            type=PlannerDecisionType.SKILL,
            skill=call,
            reason=data.get("reason"),
            raw=data,
        )
    if kind in {"task_complete", "complete", "done"}:
        return PlannerDecision(
            type=PlannerDecisionType.TASK_COMPLETE,
            reason=str(data.get("reason") or "task complete"),
            raw=data,
        )
    if kind in {"cannot_complete", "fail", "abort"}:
        return PlannerDecision(
            type=PlannerDecisionType.CANNOT_COMPLETE,
            reason=str(data.get("reason") or "cannot complete"),
            raw=data,
        )
    raise PlannerParseError(f"unsupported planner decision type {kind!r}")


def parse_planner_text(text: str, registry: SkillRegistry) -> PlannerDecision:
    blob = _extract_json(text)
    return parse_planner_payload(blob, registry)


def _as_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = _extract_json(payload)
    if not isinstance(payload, dict):
        raise PlannerParseError("planner output must be a JSON object")
    return payload


def _extract_json(text: str) -> Any:
    raw = text.strip()
    if not raw:
        raise PlannerParseError("empty planner output")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError as exc:
                raise PlannerParseError(f"invalid planner JSON: {exc}") from exc
        raise PlannerParseError("planner output is not valid JSON")
