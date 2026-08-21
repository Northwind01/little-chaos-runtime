from __future__ import annotations

import asyncio
from typing import Any

from little_chaos.backends.groot.client import GrootClient
from little_chaos.backends.sonic.client import SonicClient
from little_chaos.backends.sonic.gateway import SonicCommandGateway
from little_chaos.evaluation.base import SuccessDetector
from little_chaos.planner.base import PlannerBackend
from little_chaos.runtime.logging import TaskLogger
from little_chaos.runtime.ownership import ControlGate, ControlOwnershipError
from little_chaos.runtime.state_machine import InvalidTransition, next_after_skill_result, transition
from little_chaos.runtime.task_context import TaskContext
from little_chaos.runtime.types import (
    CommandSource,
    ControlOwner,
    Observation,
    PlannerDecisionType,
    RuntimeConfig,
    RuntimeState,
    SkillCall,
    SkillResult,
    SkillStatus,
    TaskOutcome,
)
from little_chaos.skills.base import SkillExecutor
from little_chaos.skills.registry import SkillRegistry, SkillRegistryError
from little_chaos.world.observation import WorldState


def command_source_for_skill(name: str) -> CommandSource:
    if name.startswith("vla."):
        return CommandSource.GROOT
    if name.startswith("locomotion."):
        return CommandSource.LOCOMOTION
    return CommandSource.NONE


class ExecutionRuntime:
    """High-level LittleChaos runtime.

    Orchestrates:
      CLI -> planner -> SkillRegistry -> (skill executors) -> SONIC/GR00T

    Logical command arbitration: at most one of GROOT, LOCOMOTION, NONE.
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        planner: PlannerBackend,
        skills: SkillRegistry,
        success_detector: SuccessDetector,
        world: WorldState,
        groot: GrootClient,
        sonic: SonicClient,
        ownership_gate: ControlGate | None = None,
        logger: TaskLogger | None = None,
        gateway: SonicCommandGateway | None = None,
        session_held: bool = False,
    ) -> None:
        self.config = config
        self.planner = planner
        self.skills = skills
        self.success_detector = success_detector
        self.world = world
        self.groot = groot
        self.sonic = sonic
        self.gateway = gateway
        self.ownership_gate = ownership_gate or ControlGate(
            host=config.sonic_host, port=config.sonic_port
        )
        self.logger = logger or TaskLogger(log_dir=config.log_dir)
        self.session_held = session_held

        self._stop_event = asyncio.Event()
        self._active_task: asyncio.Task[TaskOutcome] | None = None
        self._running_task_id: str | None = None
        self._last_outcome: TaskOutcome | None = None
        self._state: RuntimeState = RuntimeState.IDLE
        self._active_skill_name: str | None = None
        self._command_source = CommandSource.NONE

    async def stop(self, *, reason: str = "manual stop") -> None:
        """Interrupt an active episode. Safe; does not call the planner."""
        self._stop_event.set()
        if self._active_task is not None:
            return

    @property
    def command_source(self) -> CommandSource:
        if self.gateway is not None:
            return self.gateway.active_source
        return self._command_source

    @property
    def status(self) -> dict[str, Any]:
        ego = None
        privileged = None
        try:
            ego = self.world.ego_rgb()
        except Exception:
            ego = None
        try:
            privileged = self.world.snapshot()
        except Exception:
            privileged = None
        return {
            "running_task_id": self._running_task_id,
            "last_outcome": self._last_outcome.value if self._last_outcome else None,
            "state": self._state.value,
            "active_skill": self._active_skill_name,
            "command_source": self.command_source.value,
            "gateway_bound": bool(self.gateway.bound) if self.gateway is not None else False,
            "ego_rgb": ego is not None,
            "privileged_yaw": None if privileged is None else privileged.yaw,
            "privileged_xy": None if privileged is None else privileged.robot_xy,
        }

    def _make_observation(self, *, elapsed_s: float, recent: list[Any]) -> Observation:
        ego_rgb = self.world.ego_rgb()
        if ego_rgb is not None:
            recent.append(ego_rgb)
            if len(recent) > 4:
                del recent[0]

        snap = self.world.snapshot()
        return Observation(
            ego_rgb=ego_rgb,
            recent_frames=list(recent),
            privileged=snap,
            elapsed_s=elapsed_s,
            active_skill=None,
        )

    async def _enable_control_ownership(self) -> None:
        owner = getattr(self.ownership_gate, "owner", None)
        if owner is ControlOwner.AUTONOMOUS:
            return
        try:
            self.ownership_gate.acquire_autonomous()
        except ControlOwnershipError:
            raise

    async def _set_command_source(self, new: CommandSource) -> None:
        """Cancel previous producer, drop stale packets, idle/mode, then activate."""
        old = self.command_source
        if new is old:
            return

        if old is CommandSource.GROOT:
            try:
                await self.groot.cancel()
            except Exception:
                pass
        elif old is CommandSource.LOCOMOTION:
            try:
                await self.sonic.stop()
            except Exception:
                pass

        if self.gateway is not None:
            self.gateway.set_active_source(CommandSource.NONE)
        self._command_source = CommandSource.NONE

        # Always-forwarded idle (submit_locomotion would be dropped while source is NONE).
        try:
            await self.sonic.publish_idle()
        except Exception:
            pass

        if new is CommandSource.GROOT:
            # SONIC only latches operator_state.start inside PLANNER-mode handling.
            # enable_pose alone switches STREAMED MOTION but never starts the control
            # loop — so g1_debug never publishes and VLA waits forever on state.
            try:
                await self.sonic.enable_planner()
                await asyncio.sleep(0.5)
                await self.sonic.enable_pose()
            except Exception:
                pass
        elif new is CommandSource.LOCOMOTION:
            try:
                await self.sonic.enable_planner()
            except Exception:
                pass
        else:
            # Keep G1Deploy alive; never send stop=True.
            try:
                await self.sonic.halt_control()
            except Exception:
                pass

        if self.gateway is not None:
            self.gateway.set_active_source(new)
        self._command_source = new
        self.logger.emit("command_source", source=new.value, previous=old.value)

    async def _safe_idle(self) -> None:
        await self._set_command_source(CommandSource.NONE)

    async def execute(self, task: str) -> TaskOutcome:
        """Run one natural-language task until task-complete or stopped."""
        self._stop_event.clear()
        await self._enable_control_ownership()

        ctx = TaskContext()
        ctx.begin_task(task)
        self._running_task_id = ctx.task_id
        self._state = RuntimeState.IDLE
        self._active_skill_name = None
        self.logger.open_task(ctx.task_id)
        self.logger.emit("episode_start", task=task, task_id=ctx.task_id)

        recent_frames: list[Any] = []
        runtime_state = RuntimeState.IDLE
        active_executor: SkillExecutor | None = None
        active_call: SkillCall | None = None
        active_spec = None
        detector_task: asyncio.Task[SkillResult] | None = None
        last_detector_s: float = -1.0
        active_terminal: SkillResult | None = None

        try:
            while True:
                if self._stop_event.is_set():
                    self.logger.emit("manual_stop")
                    active_terminal = ctx.mark_cancelled(reason="manual :stop")
                    if active_executor is not None:
                        try:
                            await active_executor.cancel()
                        except Exception:
                            pass
                    await self._safe_idle()
                    self._last_outcome = TaskOutcome.CANCELLED
                    self._state = RuntimeState.IDLE
                    return TaskOutcome.CANCELLED

                elapsed_s = ctx.elapsed_s()
                observation = self._make_observation(elapsed_s=elapsed_s, recent=recent_frames)

                if runtime_state is RuntimeState.IDLE:
                    runtime_state = transition(runtime_state, RuntimeState.PLAN)
                    self._state = runtime_state

                if runtime_state is RuntimeState.PLAN:
                    decision = await self.planner.next_skill(
                        task=task,
                        observation=observation,
                        history=ctx.history_for_planner(),
                        skills=self.skills,
                    )

                    self.logger.emit(
                        "planner_decision",
                        decision_type=decision.type.value,
                        reason=decision.reason,
                    )

                    if decision.type is PlannerDecisionType.TASK_COMPLETE:
                        self.logger.emit("task_complete", reason=decision.reason)
                        await self._safe_idle()
                        self._last_outcome = TaskOutcome.SUCCESS
                        self._state = RuntimeState.IDLE
                        return TaskOutcome.SUCCESS

                    if decision.type is PlannerDecisionType.CANNOT_COMPLETE:
                        self.logger.emit("cannot_complete", reason=decision.reason)
                        await self._safe_idle()
                        self._last_outcome = TaskOutcome.CANNOT_COMPLETE
                        self._state = RuntimeState.IDLE
                        return TaskOutcome.CANNOT_COMPLETE

                    if decision.type is not PlannerDecisionType.SKILL or decision.skill is None:
                        raise SkillRegistryError(
                            f"planner returned unsupported decision: {decision}"
                        )

                    active_call = decision.skill
                    active_spec = self.skills.get(active_call.name)
                    runtime_state = transition(runtime_state, RuntimeState.START_SKILL)
                    self._state = runtime_state
                    self._active_skill_name = active_call.name

                if runtime_state is RuntimeState.START_SKILL:
                    if active_call is None:
                        raise InvalidTransition("START_SKILL without active_call")
                    ctx.begin_skill(active_call)
                    active_executor = self.skills.executor(active_call.name)
                    await self._set_command_source(command_source_for_skill(active_call.name))
                    await active_executor.start(active_call, ctx)

                    detector_task = None
                    last_detector_s = -1.0
                    runtime_state = transition(RuntimeState.START_SKILL, RuntimeState.RUNNING)
                    self._state = runtime_state

                if runtime_state is RuntimeState.RUNNING:
                    if active_executor is None or active_call is None:
                        raise InvalidTransition("RUNNING without active_executor/active_call")

                    local_result = await active_executor.poll(ctx)

                    if (
                        active_spec is not None
                        and active_spec.success_detector is not None
                        and active_spec.success_detector.lower() == "vlm"
                    ):
                        should_launch_detector = (
                            detector_task is None
                            and (ctx.skill_elapsed_s() - last_detector_s)
                            >= self.config.success_check_period_s
                        )
                        if should_launch_detector:
                            detector_task = asyncio.create_task(
                                self.success_detector.evaluate(
                                    spec=active_spec,
                                    call=active_call,
                                    observation=observation,
                                    ctx=ctx,
                                )
                            )
                            last_detector_s = ctx.skill_elapsed_s()

                        if detector_task is not None and detector_task.done():
                            detector_result = detector_task.result()
                            if detector_result.status in {
                                SkillStatus.SUCCESS,
                                SkillStatus.FAILURE,
                                SkillStatus.CANCELLED,
                            }:
                                local_result = detector_result

                    if local_result.status in {
                        SkillStatus.SUCCESS,
                        SkillStatus.FAILURE,
                        SkillStatus.CANCELLED,
                    }:
                        active_terminal = local_result
                        ctx.end_skill(active_terminal)
                        runtime_state = transition(RuntimeState.RUNNING, RuntimeState.STOP_SKILL)
                        self._state = runtime_state

                if runtime_state is RuntimeState.STOP_SKILL:
                    if active_executor is not None:
                        try:
                            await active_executor.cancel()
                        except Exception:
                            pass
                    await self._set_command_source(CommandSource.NONE)

                    if active_terminal is None:
                        active_terminal = SkillResult(
                            status=SkillStatus.CANCELLED, reason="no terminal result"
                        )

                    runtime_state = next_after_skill_result(
                        active_terminal.status,
                        manual_stop=ctx.stop_requested,
                    )
                    self._state = runtime_state

                    if (
                        runtime_state is RuntimeState.IDLE
                        and active_terminal.status is SkillStatus.CANCELLED
                    ):
                        self._last_outcome = TaskOutcome.CANCELLED
                        self._state = RuntimeState.IDLE
                        return TaskOutcome.CANCELLED

                await asyncio.sleep(self.config.tick_s)

        finally:
            try:
                await self._set_command_source(CommandSource.NONE)
            except Exception:
                pass
            if not self.session_held:
                try:
                    self.ownership_gate.release()
                except Exception:
                    pass
            self.logger.emit("episode_end", task_id=ctx.task_id)
            self.logger.close()
            self._last_outcome = self._last_outcome or TaskOutcome.CANCELLED
            self._active_skill_name = None
            self._running_task_id = None
