"""HTTP client boundary for a Vesta-style planner. No SONIC/GR00T imports."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from little_chaos.planner.base import PlannerBackend, PlannerParseError, parse_planner_payload
from little_chaos.planner.prompts import SYSTEM_PROMPT, render_user_prompt
from little_chaos.runtime.types import Observation, PlannerDecision, RuntimeConfig
from little_chaos.skills.registry import SkillRegistry


class VestaPlannerError(RuntimeError):
    pass


class VestaPlanner(PlannerBackend):
    """Model-client wrapper. Does not assume a public Vesta SDK."""

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("VESTA_ENDPOINT")
        self.model = model or os.environ.get("VESTA_MODEL")
        self.timeout_s = timeout_s

    async def next_skill(
        self,
        task: str,
        observation: Observation,
        history: list[dict[str, Any]],
        skills: SkillRegistry,
    ) -> PlannerDecision:
        if not self.endpoint:
            raise VestaPlannerError(
                "PLANNER_BACKEND=vesta but VESTA_ENDPOINT is not set. "
                "Do not silently fall back to the mock planner."
            )
        prompt = render_user_prompt(task, observation, history, skills)
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "input": prompt,
            "task": task,
            "skills": skills.planner_catalog(),
            "history": history,
            "observation": {
                "elapsed_s": observation.elapsed_s,
                "privileged": observation.privileged.as_log_dict(),
            },
        }
        raw = _http_json(self.endpoint, payload, timeout_s=self.timeout_s)
        try:
            return parse_planner_payload(_unwrap_model_output(raw), skills)
        except PlannerParseError as exc:
            raise PlannerParseError(f"invalid Vesta output: {exc}") from exc


def _unwrap_model_output(raw: Any) -> Any:
    if isinstance(raw, dict):
        for key in ("decision", "output", "content", "text", "message"):
            if key in raw:
                value = raw[key]
                if isinstance(value, dict) and "content" in value:
                    return value["content"]
                return value
    return raw


def _http_json(url: str, payload: dict[str, Any], timeout_s: float) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise VestaPlannerError(f"Vesta request failed: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_planner(config: RuntimeConfig) -> PlannerBackend:
    backend = (config.planner_backend or "mock").strip().lower()
    if backend == "mock":
        from little_chaos.planner.mock import MockPlanner

        return MockPlanner()
    if backend == "vesta":
        return VestaPlanner(endpoint=config.vesta_endpoint, model=config.vesta_model)
    raise VestaPlannerError(f"unknown PLANNER_BACKEND={backend!r} (use mock or vesta)")
