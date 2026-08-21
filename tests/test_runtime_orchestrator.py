import asyncio

from little_chaos.backends.groot.client import GrootClient
from little_chaos.backends.sonic.client import SonicClient
from little_chaos.backends.sonic.gateway import SonicCommandGateway
from little_chaos.evaluation.base import SuccessDetector
from little_chaos.planner.base import PlannerDecision
from little_chaos.planner.mock import MockPlanner
from little_chaos.runtime.logging import TaskLogger
from little_chaos.runtime.orchestrator import ExecutionRuntime, command_source_for_skill
from little_chaos.runtime.types import (
    CommandSource,
    PlannerDecisionType,
    RuntimeConfig,
    SkillCall,
    SkillResult,
    SkillStatus,
    TaskOutcome,
)
from little_chaos.skills.locomotion import RetreatExecutor, StopExecutor, TurnAroundExecutor, WalkExecutor
from little_chaos.skills.registry import build_default_registry
from little_chaos.skills.vla import VlaFindGirlExecutor, VlaGoToGirlExecutor
from little_chaos.world.observation import StaticWorld


class InstantSuccessDetector(SuccessDetector):
    def __init__(self, *, status: SkillStatus = SkillStatus.SUCCESS) -> None:
        self._status = status

    async def evaluate(self, spec, call, observation, ctx):  # type: ignore[override]
        return SkillResult(status=self._status, reason="detector", confidence=1.0)


class RunningDetector(SuccessDetector):
    async def evaluate(self, spec, call, observation, ctx):  # type: ignore[override]
        return SkillResult(status=SkillStatus.RUNNING, reason="running", confidence=0.2)


class FakeGate:
    owner = None

    def acquire_autonomous(self) -> None:
        return

    def release(self) -> None:
        return


def _executors(config, world, sonic, groot):
    return {
        "vla.find_girl": VlaFindGirlExecutor(groot=groot, timeout_s=config.vla_timeout_s),
        "vla.go_to_girl": VlaGoToGirlExecutor(groot=groot, timeout_s=config.vla_timeout_s),
        "locomotion.walk": WalkExecutor(world=world, sonic=sonic, timeout_s=1.0),
        "locomotion.stop": StopExecutor(world=world, sonic=sonic, timeout_s=1.0),
        "locomotion.retreat": RetreatExecutor(
            world=world,
            sonic=sonic,
            timeout_s=1.0,
            retreat_distance_min_m=config.retreat_min_m,
            retreat_distance_max_m=config.retreat_max_m,
        ),
        "locomotion.turn_around": TurnAroundExecutor(
            world=world,
            sonic=sonic,
            timeout_s=1.0,
            yaw_tolerance_rad=config.turn_yaw_tolerance_rad,
        ),
    }


def _build_runtime(*, detector: SuccessDetector, planner=None, gateway=None):
    config = RuntimeConfig(
        tick_s=0.002,
        success_check_period_s=0.001,
        vla_timeout_s=10.0,
        walk_max_duration_s=0.5,
        turn_timeout_s=1.0,
        retreat_min_m=0.1,
        retreat_max_m=1.0,
        log_dir="logs/runtime-test",
    )
    groot_msgs: list[str] = []
    if gateway is None:
        sonic = SonicClient(send=lambda _b: None)
    else:
        sonic = SonicClient(gateway=gateway)
    groot = GrootClient(send=lambda s: groot_msgs.append(s))
    world = StaticWorld()
    skills = build_default_registry(
        executors=_executors(config, world, sonic, groot),
        config=config,
    )
    runtime = ExecutionRuntime(
        config=config,
        planner=planner or MockPlanner(),
        skills=skills,
        success_detector=detector,
        world=world,
        groot=groot,
        sonic=sonic,
        ownership_gate=FakeGate(),  # type: ignore[arg-type]
        logger=TaskLogger(log_dir=config.log_dir),
        gateway=gateway,
    )
    return runtime, groot_msgs


def test_runtime_vla_sequence_success() -> None:
    async def run():
        runtime, msgs = _build_runtime(detector=InstantSuccessDetector())
        outcome = await runtime.execute("find the girl and go to her")
        return outcome, msgs

    outcome, msgs = asyncio.run(run())
    assert outcome is TaskOutcome.SUCCESS
    assert any(m.startswith("prompt:Find the girl") for m in msgs)
    assert any(m.startswith("prompt:Go to the girl") for m in msgs)


def test_runtime_manual_stop_cancels_episode() -> None:
    async def run() -> TaskOutcome:
        runtime, _ = _build_runtime(detector=RunningDetector())
        task = asyncio.create_task(runtime.execute("find the girl and go to her"))
        await asyncio.sleep(0.01)
        await runtime.stop()
        return await task

    outcome = asyncio.run(run())
    assert outcome is TaskOutcome.CANCELLED


def test_command_source_for_skill() -> None:
    assert command_source_for_skill("vla.find_girl") is CommandSource.GROOT
    assert command_source_for_skill("locomotion.walk") is CommandSource.LOCOMOTION
    assert command_source_for_skill("other") is CommandSource.NONE


def test_source_transition_cancels_groot_then_enables_locomotion() -> None:
    sent: list[bytes] = []
    gw = SonicCommandGateway(forward=sent.append)
    planner = MockPlanner(
        sequences={
            "mix vla then stop": [
                PlannerDecision(
                    type=PlannerDecisionType.SKILL,
                    skill=SkillCall("vla.find_girl", {}),
                ),
                PlannerDecision(
                    type=PlannerDecisionType.SKILL,
                    skill=SkillCall("locomotion.stop", {}),
                ),
                PlannerDecision(
                    type=PlannerDecisionType.TASK_COMPLETE,
                    reason="done",
                ),
            ]
        }
    )

    async def run():
        runtime, msgs = _build_runtime(
            detector=InstantSuccessDetector(),
            planner=planner,
            gateway=gw,
        )
        outcome = await runtime.execute("mix vla then stop")
        return outcome, msgs, runtime.command_source

    outcome, msgs, source = asyncio.run(run())
    assert outcome is TaskOutcome.SUCCESS
    assert any(m.startswith("prompt:Find the girl") for m in msgs)
    assert "p" in msgs
    assert source is CommandSource.NONE
    assert gw.control_sent >= 1
