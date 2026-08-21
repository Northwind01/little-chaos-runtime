"""SONIC locomotion vocabulary and world-frame command math."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Sequence


class LocomotionMode(IntEnum):
    """Mirrors pico_manager_thread_server.LocomotionMode."""

    IDLE = 0
    SLOW_WALK = 1
    WALK = 2
    RUN = 3


WALK_DIRECTIONS = ("forward", "backward", "left", "right")
WALK_SPEEDS = ("slow", "normal")

SPEED_TO_MODE = {
    "slow": (LocomotionMode.SLOW_WALK, 0.35),
    "normal": (LocomotionMode.WALK, -1.0),
}


@dataclass(frozen=True)
class PlannerCommand:
    mode: int
    movement: tuple[float, float, float]
    facing: tuple[float, float, float]
    speed: float = -1.0
    height: float = -1.0


def wrap_yaw(yaw: float) -> float:
    """Wrap radians to (-pi, pi]."""
    wrapped = (float(yaw) + math.pi) % (2.0 * math.pi)
    if wrapped <= 0.0:
        wrapped += 2.0 * math.pi
    return wrapped - math.pi


def yaw_error(current: float, target: float) -> float:
    return wrap_yaw(target - current)


def facing_from_yaw(yaw: float) -> tuple[float, float, float]:
    return (math.cos(float(yaw)), math.sin(float(yaw)), 0.0)


def movement_from_direction(direction: str, yaw: float) -> tuple[float, float, float]:
    fx, fy, _ = facing_from_yaw(yaw)
    key = direction.strip().lower()
    if key == "forward":
        return (fx, fy, 0.0)
    if key == "backward":
        return (-fx, -fy, 0.0)
    if key == "left":
        return (-fy, fx, 0.0)
    if key == "right":
        return (fy, -fx, 0.0)
    raise ValueError(f"unsupported walk direction {direction!r}")


def idle_command(yaw: float | None = None) -> PlannerCommand:
    facing = facing_from_yaw(0.0 if yaw is None else yaw)
    return PlannerCommand(
        mode=int(LocomotionMode.IDLE),
        movement=(0.0, 0.0, 0.0),
        facing=facing,
        speed=-1.0,
        height=-1.0,
    )


def walk_command(direction: str, speed_name: str, yaw: float) -> PlannerCommand:
    mode, speed = SPEED_TO_MODE[speed_name]
    movement = movement_from_direction(direction, yaw)
    facing = facing_from_yaw(yaw)
    return PlannerCommand(
        mode=int(mode),
        movement=movement,
        facing=facing,
        speed=float(speed),
        height=-1.0,
    )


def turn_command(target_yaw: float) -> PlannerCommand:
    return PlannerCommand(
        mode=int(LocomotionMode.SLOW_WALK),
        movement=(0.0, 0.0, 0.0),
        facing=facing_from_yaw(target_yaw),
        speed=0.2,
        height=-1.0,
    )


def retreat_command(yaw: float) -> PlannerCommand:
    return walk_command("backward", "slow", yaw)


def xy_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def turn_around_target(initial_yaw: float) -> float:
    return wrap_yaw(initial_yaw + math.pi)
