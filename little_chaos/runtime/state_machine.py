"""Explicit runtime state-machine transitions."""

from __future__ import annotations

from little_chaos.runtime.types import RuntimeState, SkillStatus

_ALLOWED: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.IDLE: frozenset({RuntimeState.PLAN}),
    RuntimeState.PLAN: frozenset(
        {RuntimeState.START_SKILL, RuntimeState.IDLE, RuntimeState.STOP_SKILL}
    ),
    RuntimeState.START_SKILL: frozenset({RuntimeState.RUNNING, RuntimeState.IDLE}),
    RuntimeState.RUNNING: frozenset(
        {RuntimeState.STOP_SKILL, RuntimeState.IDLE, RuntimeState.PLAN}
    ),
    RuntimeState.STOP_SKILL: frozenset({RuntimeState.PLAN, RuntimeState.IDLE}),
}

TERMINAL_SKILL = frozenset(
    {
        SkillStatus.SUCCESS,
        SkillStatus.FAILURE,
        SkillStatus.CANCELLED,
    }
)


class InvalidTransition(RuntimeError):
    pass


def can_transition(current: RuntimeState, nxt: RuntimeState) -> bool:
    return nxt in _ALLOWED[current]


def transition(current: RuntimeState, nxt: RuntimeState) -> RuntimeState:
    if not can_transition(current, nxt):
        raise InvalidTransition(f"illegal runtime transition {current.value} -> {nxt.value}")
    return nxt


def next_after_skill_result(status: SkillStatus, *, manual_stop: bool) -> RuntimeState:
    if manual_stop or status is SkillStatus.CANCELLED:
        return RuntimeState.IDLE
    if status in TERMINAL_SKILL or status is SkillStatus.UNCERTAIN:
        return RuntimeState.PLAN
    return RuntimeState.RUNNING
