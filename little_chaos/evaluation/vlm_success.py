"""Short, stable VLM success prompts. The detector never commands the robot."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from little_chaos.evaluation.base import SuccessDetector
from little_chaos.evaluation.types import DetectorSchemaError, parse_detector_payload
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import Observation, SkillCall, SkillResult, SkillSpec, SkillStatus

FIND_GIRL_CONDITION = "the girl has been visibly and confidently located in the robot's current observation"

GO_TO_GIRL_CONDITION = (
    "the robot appears to have reached an appropriate standing distance "
    "from the girl without obvious collision"
)

CONDITIONS = {
    "vla.find_girl": FIND_GIRL_CONDITION,
    "vla.go_to_girl": GO_TO_GIRL_CONDITION,
}

DETECTOR_PROMPT = """You are a success detector for a humanoid robot skill.
Return only JSON:
{"status":"RUNNING|SUCCESS|FAILURE|UNCERTAIN","confidence":0.0,"reason":"..."}
Do not command the robot. Do not invent extra skills.
SUCCESS only if the expected condition is clearly met.
FAILURE if the skill has clearly failed.
RUNNING if execution should continue.
UNCERTAIN if the image is inconclusive.
"""


class VlmSuccessDetector(SuccessDetector):
    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        timeout_s: float = 15.0,
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("VLM_ENDPOINT")
        self.model = model or os.environ.get("VLM_MODEL")
        self.timeout_s = timeout_s
        self._client = client

    async def evaluate(
        self,
        spec: SkillSpec,
        call: SkillCall,
        observation: Observation,
        ctx: TaskContext,
    ) -> SkillResult:
        if self._client is not None:
            payload = await self._client(spec, call, observation, ctx)
            return parse_detector_payload(payload)
        if not self.endpoint:
            return SkillResult(
                status=SkillStatus.UNCERTAIN,
                reason="VLM_ENDPOINT is not configured",
                confidence=0.0,
            )
        body = {
            "model": self.model,
            "system": DETECTOR_PROMPT,
            "skill": spec.name,
            "description": spec.description,
            "expected_success": CONDITIONS.get(spec.name, spec.description),
            "elapsed_s": observation.elapsed_s,
            "history": ctx.history_for_planner(),
            "has_ego_rgb": observation.ego_rgb is not None,
            "recent_frame_count": len(observation.recent_frames),
        }
        raw = _http_json(self.endpoint, body, self.timeout_s)
        if isinstance(raw, dict):
            try:
                return parse_detector_payload(raw)
            except DetectorSchemaError:
                inner = raw.get("output") or raw.get("content") or raw.get("text")
                if isinstance(inner, str):
                    raw = inner
                elif isinstance(inner, dict):
                    return parse_detector_payload(inner)
        if isinstance(raw, str):
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return parse_detector_payload(json.loads(raw[start : end + 1]))
        raise DetectorSchemaError(f"unrecognized VLM detector payload: {raw!r}")


def _http_json(url: str, payload: dict[str, Any], timeout_s: float) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            text = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        return {
            "status": "UNCERTAIN",
            "confidence": 0.0,
            "reason": f"VLM request failed: {exc}",
        }
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
