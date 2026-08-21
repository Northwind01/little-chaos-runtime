"""Core typed contracts for the LittleChaos execution runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SkillStatus(Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


class RuntimeState(Enum):
    IDLE = "idle"
    PLAN = "plan"
    START_SKILL = "start_skill"
    RUNNING = "running"
    STOP_SKILL = "stop_skill"


class ControlOwner(Enum):
    TELEOP = "teleop"
    AUTONOMOUS = "autonomous"
    IDLE = "idle"


class CommandSource(Enum):
    """Who may currently forward packed SONIC messages through the gateway."""

    NONE = "none"
    GROOT = "groot"
    LOCOMOTION = "locomotion"


class PlannerDecisionType(Enum):
    SKILL = "skill"
    TASK_COMPLETE = "task_complete"
    CANNOT_COMPLETE = "cannot_complete"


class TaskOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    CANNOT_COMPLETE = "cannot_complete"


@dataclass
class SkillCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    status: SkillStatus
    reason: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    executor_type: str
    timeout_s: float
    interruptible: bool
    canonical_instruction: str | None = None
    success_detector: str | None = None
    argument_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlannerDecision:
    type: PlannerDecisionType
    skill: SkillCall | None = None
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PrivilegedSnapshot:
    robot_xy: tuple[float, float] | None = None
    girl_xy: tuple[float, float] | None = None
    robot_girl_distance: float | None = None
    girl_visible: bool | None = None
    collision: bool = False
    upright: bool = True
    fallen: bool = False
    yaw: float | None = None
    robot_xyz: tuple[float, float, float] | None = None

    def as_log_dict(self) -> dict[str, Any]:
        return {
            "robot_xy": list(self.robot_xy) if self.robot_xy is not None else None,
            "girl_xy": list(self.girl_xy) if self.girl_xy is not None else None,
            "girl_distance": self.robot_girl_distance,
            "girl_visible": self.girl_visible,
            "collision": self.collision,
            "upright": self.upright,
            "fallen": self.fallen,
            "yaw": self.yaw,
        }


@dataclass
class Observation:
    ego_rgb: Any = None
    recent_frames: list[Any] = field(default_factory=list)
    privileged: PrivilegedSnapshot = field(default_factory=PrivilegedSnapshot)
    elapsed_s: float = 0.0
    active_skill: SkillCall | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    success_check_period_s: float = 0.75
    tick_s: float = 0.05
    max_skills_per_task: int = 20
    walk_max_duration_s: float = 5.0
    retreat_min_m: float = 0.1
    retreat_max_m: float = 1.0
    turn_yaw_tolerance_rad: float = 0.12
    turn_timeout_s: float = 15.0
    vla_timeout_s: float = 20.0
    planner_backend: str = "mock"
    vesta_endpoint: str | None = None
    vesta_model: str | None = None
    vlm_endpoint: str | None = None
    vlm_model: str | None = None
    log_dir: str = "logs/runtime"
    sonic_host: str = "127.0.0.1"
    sonic_port: int = 5556
    camera_host: str = "127.0.0.1"
    camera_port: int = 5555
    camera_name: str = "ego_view"
    state_host: str = "127.0.0.1"
    state_port: int = 5557
    groot_keyboard_host: str = "127.0.0.1"
    groot_keyboard_port: int = 5580
    groot_policy_host: str = "127.0.0.1"
    groot_policy_port: int = 5550
    groot_ingest_host: str = "127.0.0.1"
    groot_ingest_port: int = 5561
    privileged_state_host: str = "127.0.0.1"
    privileged_state_port: int = 5559
    lab_root: str | None = None

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        import os

        def _float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return default if raw is None or raw == "" else float(raw)

        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return default if raw is None or raw == "" else int(raw)

        def _opt(name: str) -> str | None:
            raw = os.environ.get(name)
            return raw if raw else None

        return cls(
            success_check_period_s=_float("SUCCESS_CHECK_PERIOD_S", 0.75),
            tick_s=_float("RUNTIME_TICK_S", 0.05),
            max_skills_per_task=_int("MAX_SKILLS_PER_TASK", 20),
            walk_max_duration_s=_float("WALK_MAX_DURATION_S", 5.0),
            retreat_min_m=_float("RETREAT_MIN_M", 0.1),
            retreat_max_m=_float("RETREAT_MAX_M", 1.0),
            turn_yaw_tolerance_rad=_float("TURN_YAW_TOLERANCE_RAD", 0.12),
            turn_timeout_s=_float("TURN_TIMEOUT_S", 15.0),
            vla_timeout_s=_float("VLA_TIMEOUT_S", 20.0),
            planner_backend=os.environ.get("PLANNER_BACKEND", "mock").strip().lower(),
            vesta_endpoint=_opt("VESTA_ENDPOINT"),
            vesta_model=_opt("VESTA_MODEL"),
            vlm_endpoint=_opt("VLM_ENDPOINT"),
            vlm_model=_opt("VLM_MODEL"),
            log_dir=os.environ.get("RUNTIME_LOG_DIR", "logs/runtime"),
            sonic_host=os.environ.get("SONIC_HOST", "127.0.0.1"),
            sonic_port=_int("SONIC_PORT", 5556),
            camera_host=os.environ.get("CAMERA_HOST", "127.0.0.1"),
            camera_port=_int("CAMERA_PORT", 5555),
            camera_name=os.environ.get("EGO_CAMERA_NAME", "ego_view"),
            state_host=os.environ.get("STATE_HOST", "127.0.0.1"),
            state_port=_int("STATE_PORT", 5557),
            groot_keyboard_host=os.environ.get("KEYBOARD_HOST", "127.0.0.1"),
            groot_keyboard_port=_int("KEYBOARD_PORT", 5580),
            groot_policy_host=os.environ.get("POLICY_HOST", "127.0.0.1"),
            groot_policy_port=_int("POLICY_PORT", 5550),
            groot_ingest_host=os.environ.get("SONIC_GROOT_INGEST_HOST", "127.0.0.1"),
            groot_ingest_port=_int("SONIC_GROOT_INGEST_PORT", 5561),
            privileged_state_host=os.environ.get("PRIVILEGED_STATE_HOST", "127.0.0.1"),
            privileged_state_port=_int("PRIVILEGED_STATE_PORT", 5559),
            lab_root=_opt("LAB_ROOT") or _opt("GR00T_WBC_LAB"),
        )
