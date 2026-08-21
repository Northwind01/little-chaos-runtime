"""Stable planner prompt text. One next skill, registered names only."""

from __future__ import annotations

from typing import Any

from little_chaos.runtime.types import Observation
from little_chaos.skills.registry import SkillRegistry

SYSTEM_PROMPT = """You are the LittleChaos high-level planner.

Choose exactly one next registered skill, or report that the user task is
complete / cannot be completed.

Rules:
- Only choose skills from AVAILABLE SKILLS.
- Do not invent robot capabilities.
- Do not output low-level motor commands or SONIC packets.
- Do not output Python, function names, or free-form GR00T prompts.
- Prefer VLA semantic skills when they directly match the task
  (vla.find_girl, vla.go_to_girl).
- Use locomotion skills only for simple recovery, reorientation, or
  bounded movement (walk, stop, retreat, turn_around).
- Output exactly one next action.
- GR00T language strings are owned by the skill registry, not by you.

Return only JSON in one of these forms:
{"type":"skill","skill":"vla.find_girl","arguments":{}}
{"type":"task_complete","reason":"..."}
{"type":"cannot_complete","reason":"..."}
"""


def render_user_prompt(
    task: str,
    observation: Observation,
    history: list[dict[str, Any]],
    skills: SkillRegistry,
) -> str:
    catalog_lines = []
    for spec in skills.specs():
        catalog_lines.append(
            f"- {spec.name}: {spec.description} args={spec.argument_schema or {}}"
        )
    privileged = observation.privileged
    obs_lines = [
        f"elapsed_s={observation.elapsed_s:.2f}",
        f"active_skill={observation.active_skill.name if observation.active_skill else None}",
        f"collision={privileged.collision}",
        f"fallen={privileged.fallen}",
        f"upright={privileged.upright}",
        f"yaw={privileged.yaw}",
        f"girl_distance={privileged.robot_girl_distance}",
        f"girl_visible={privileged.girl_visible}",
    ]
    history_lines = []
    for row in history[-12:]:
        history_lines.append(str(row))
    return "\n".join(
        [
            "USER TASK",
            task.strip(),
            "",
            "CURRENT OBSERVATION",
            *obs_lines,
            "",
            "RECENT EXECUTION HISTORY",
            *(history_lines or ["(none)"]),
            "",
            "AVAILABLE SKILLS",
            *catalog_lines,
        ]
    )
