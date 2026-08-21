"""Assemble ExecutionRuntime for offline demo or live autonomous sessions."""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable

from little_chaos.backends.groot.client import GrootClient
from little_chaos.backends.sonic.client import SonicClient
from little_chaos.backends.sonic.gateway import SonicCommandGateway
from little_chaos.backends.sonic.locomotion import LocomotionMode, PlannerCommand, wrap_yaw
from little_chaos.evaluation.base import SuccessDetector
from little_chaos.evaluation.vlm_success import VlmSuccessDetector
from little_chaos.planner.vesta import build_planner
from little_chaos.runtime.logging import TaskLogger
from little_chaos.runtime.orchestrator import ExecutionRuntime
from little_chaos.runtime.ownership import ControlGate, ControlOwnershipError
from little_chaos.runtime.types import RuntimeConfig, SkillResult, SkillStatus
from little_chaos.skills.locomotion import RetreatExecutor, StopExecutor, TurnAroundExecutor, WalkExecutor
from little_chaos.skills.registry import build_default_registry
from little_chaos.skills.vla import VlaFindGirlExecutor, VlaGoToGirlExecutor
from little_chaos.world.mujoco_state import CompositeWorld
from little_chaos.world.observation import EgoRgbSource, StaticWorld
from little_chaos.world.privileged import PrivilegedStateSource


class SimulatedWorld(StaticWorld):
    """Offline simulation: advances pose based on the last SONIC command."""

    def __init__(self, *, sonic: SonicClient) -> None:  # type: ignore[override]
        super().__init__()
        self._sonic = sonic
        self._last_t = time.monotonic()

    def _maybe_step(self) -> None:
        now = time.monotonic()
        dt = max(0.0, now - self._last_t)
        self._last_t = now
        if dt <= 0:
            return

        cmd: PlannerCommand | None = self._sonic.last_command
        if cmd is None or cmd.mode == int(LocomotionMode.IDLE):
            return

        is_turn = abs(cmd.movement[0]) < 1e-6 and abs(cmd.movement[1]) < 1e-6
        if is_turn:
            target_yaw = float(math.atan2(cmd.facing[1], cmd.facing[0]))
            err = wrap_yaw(target_yaw - self.pose.yaw)
            max_turn_rate = 2.0
            step = max(-max_turn_rate * dt, min(max_turn_rate * dt, err))
            self.pose.yaw = wrap_yaw(self.pose.yaw + step)
            return

        speed = float(cmd.speed) if cmd.speed > 0 else 0.35
        vx, vy, _ = cmd.movement
        self.pose.x += float(vx) * speed * dt
        self.pose.y += float(vy) * speed * dt

    def snapshot(self):  # type: ignore[override]
        self._maybe_step()
        return super().snapshot()


class DemoDetector(SuccessDetector):
    """Deterministic detector for local demos/tests. Never commands the robot."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    async def evaluate(self, spec, call, observation, ctx):  # type: ignore[override]
        k = spec.name
        self._seen[k] = self._seen.get(k, 0) + 1
        if self._seen[k] >= 2:
            return SkillResult(
                status=SkillStatus.SUCCESS,
                reason=f"demo detector: {k} satisfied",
                confidence=1.0,
            )
        return SkillResult(
            status=SkillStatus.RUNNING,
            reason=f"demo detector: waiting ({self._seen[k]})",
            confidence=0.2,
        )


class LiveTimeoutDetector(SuccessDetector):
    """Live default without a VLM: never declare success.

    Lets VLA skills run until the executor timeout so SONIC/inference actually
    move the robot. Offline demos keep using ``DemoDetector``.
    """

    async def evaluate(self, spec, call, observation, ctx):  # type: ignore[override]
        return SkillResult(
            status=SkillStatus.RUNNING,
            reason="live detector: waiting for timeout or VLM endpoint",
            confidence=0.0,
        )


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _default_detector(config: RuntimeConfig, *, live: bool) -> SuccessDetector:
    if config.vlm_endpoint:
        return VlmSuccessDetector(endpoint=config.vlm_endpoint, model=config.vlm_model)
    if live:
        return LiveTimeoutDetector()
    return DemoDetector()


def _attach_executors(
    *,
    config: RuntimeConfig,
    world: Any,
    sonic: SonicClient,
    groot: GrootClient,
) -> dict:
    walk_timeout = config.walk_max_duration_s + 1.0
    return {
        "vla.find_girl": VlaFindGirlExecutor(groot=groot, timeout_s=config.vla_timeout_s),
        "vla.go_to_girl": VlaGoToGirlExecutor(groot=groot, timeout_s=config.vla_timeout_s),
        "locomotion.walk": WalkExecutor(world=world, sonic=sonic, timeout_s=walk_timeout),
        "locomotion.stop": StopExecutor(world=world, sonic=sonic, timeout_s=2.0),
        "locomotion.retreat": RetreatExecutor(
            world=world,
            sonic=sonic,
            timeout_s=20.0,
            retreat_distance_min_m=config.retreat_min_m,
            retreat_distance_max_m=config.retreat_max_m,
        ),
        "locomotion.turn_around": TurnAroundExecutor(
            world=world,
            sonic=sonic,
            timeout_s=config.turn_timeout_s,
            yaw_tolerance_rad=config.turn_yaw_tolerance_rad,
        ),
    }


def build_runtime(
    config: RuntimeConfig | None = None,
    *,
    live: bool | None = None,
    world: Any | None = None,
    sonic: SonicClient | None = None,
    groot: GrootClient | None = None,
    gateway: SonicCommandGateway | None = None,
    detector: SuccessDetector | None = None,
    planner: Any | None = None,
    ownership_gate: ControlGate | None = None,
    logger: TaskLogger | None = None,
    connect_live: bool = True,
) -> ExecutionRuntime:
    cfg = config or RuntimeConfig.from_env()
    if live is None:
        live = _bool_env("LITTLECHAOS_LIVE", False)

    planner = planner or build_planner(cfg)
    detector = detector or _default_detector(cfg, live=bool(live))
    gate = ownership_gate or ControlGate(host=cfg.sonic_host, port=cfg.sonic_port)
    session_held = False
    closers: list[Callable[[], None]] = []

    if live:
        if connect_live:
            try:
                gate.acquire_autonomous()
            except ControlOwnershipError:
                raise
        if gateway is None:
            gateway = SonicCommandGateway(
                host=cfg.sonic_host,
                sonic_port=cfg.sonic_port,
                groot_ingest_host=cfg.groot_ingest_host,
                groot_ingest_port=cfg.groot_ingest_port,
            )
            if connect_live:
                gateway.bind()
        session_held = True
        if sonic is None:
            sonic = SonicClient(host=cfg.sonic_host, port=cfg.sonic_port, gateway=gateway)
            sonic.connect()
        if groot is None:
            groot = GrootClient(
                host=cfg.groot_keyboard_host,
                port=cfg.groot_keyboard_port,
                bind=True,
            )
            if connect_live:
                groot.connect()
        if world is None:
            rgb = EgoRgbSource(
                host=cfg.camera_host,
                port=cfg.camera_port,
                camera_name=cfg.camera_name,
                color_order="rgb",
            )
            priv = PrivilegedStateSource(
                host=cfg.privileged_state_host,
                port=cfg.privileged_state_port,
            )
            if connect_live:
                try:
                    rgb.connect()
                except Exception as exc:
                    if gateway is not None:
                        gateway.close()
                    raise RuntimeError(
                        f"live ego RGB failed: {exc}. Set PYTHONPATH to lab src/ + GR00T-WholeBodyControl."
                    ) from exc
                try:
                    priv.connect()
                except Exception as exc:
                    rgb.close()
                    if gateway is not None:
                        gateway.close()
                    raise RuntimeError(f"live privileged state failed: {exc}") from exc
            world = CompositeWorld(rgb_source=rgb, state_source=priv)
            closers.extend([rgb.close, priv.close])
    else:
        sonic_send = None if _bool_env("LITTLECHAOS_LIVE_SONIC") else (lambda _pkt: None)
        groot_send = None if _bool_env("LITTLECHAOS_LIVE_GR00T") else (lambda _msg: None)
        if sonic is None:
            sonic = SonicClient(host=cfg.sonic_host, port=cfg.sonic_port, send=sonic_send)
        if groot is None:
            groot = GrootClient(
                host=cfg.groot_keyboard_host,
                port=cfg.groot_keyboard_port,
                send=groot_send,
            )
        if world is None:
            world = SimulatedWorld(sonic=sonic)
            world.pose.yaw = 0.0
            world.privileged.robot_xy = (0.0, 0.0)

    skills = build_default_registry(
        executors=_attach_executors(config=cfg, world=world, sonic=sonic, groot=groot),
        config=cfg,
    )
    runtime = ExecutionRuntime(
        config=cfg,
        planner=planner,
        skills=skills,
        success_detector=detector,
        world=world,
        groot=groot,
        sonic=sonic,
        ownership_gate=gate,
        logger=logger or TaskLogger(log_dir=cfg.log_dir),
        gateway=gateway,
        session_held=session_held,
    )
    runtime._resource_closers = closers  # type: ignore[attr-defined]
    return runtime


def close_runtime(runtime: ExecutionRuntime) -> None:
    gateway = runtime.gateway
    if gateway is not None:
        try:
            gateway.close()
        except Exception:
            pass
    try:
        runtime.groot.close()
    except Exception:
        pass
    try:
        runtime.sonic.close()
    except Exception:
        pass
    for closer in getattr(runtime, "_resource_closers", []):
        try:
            closer()
        except Exception:
            pass
    try:
        runtime.ownership_gate.release()
    except Exception:
        pass
