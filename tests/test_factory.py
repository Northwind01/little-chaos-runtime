from little_chaos.backends.sonic.gateway import SonicCommandGateway
from little_chaos.cli.factory import build_runtime
from little_chaos.runtime.types import ControlOwner, RuntimeConfig
from little_chaos.world.mujoco_state import CompositeWorld
from little_chaos.world.observation import StaticWorld


class FakeGate:
    def __init__(self) -> None:
        self.owner = ControlOwner.IDLE

    def acquire_autonomous(self) -> None:
        self.owner = ControlOwner.AUTONOMOUS

    def release(self) -> None:
        self.owner = ControlOwner.IDLE


def test_factory_offline_uses_simulated_world() -> None:
    runtime = build_runtime(RuntimeConfig(log_dir="logs/runtime-test"), live=False, connect_live=False)
    assert runtime.gateway is None
    assert runtime.session_held is False
    assert runtime.world.snapshot().robot_xy is not None


def test_factory_live_uses_composite_world() -> None:
    rgb = StaticWorld()
    rgb.frame = object()
    state = StaticWorld()
    world = CompositeWorld(rgb_source=rgb, state_source=state)
    gw = SonicCommandGateway(forward=lambda _b: None)
    runtime = build_runtime(
        RuntimeConfig(log_dir="logs/runtime-test"),
        live=True,
        connect_live=False,
        world=world,
        gateway=gw,
        ownership_gate=FakeGate(),  # type: ignore[arg-type]
    )
    assert runtime.world is world
    assert runtime.gateway is gw
    assert runtime.session_held is True
    assert isinstance(runtime.world, CompositeWorld)
