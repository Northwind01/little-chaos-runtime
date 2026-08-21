from little_chaos.backends.sonic.client import SonicClient
from little_chaos.backends.sonic.protocol import build_command_message
from little_chaos.cli.factory import DemoDetector, LiveTimeoutDetector, _default_detector
from little_chaos.runtime.types import RuntimeConfig
import asyncio


def test_halt_control_does_not_send_operator_stop() -> None:
    sent: list[bytes] = []

    class Gw:
        def publish_control(self, packet: bytes) -> None:
            sent.append(packet)

        def submit_locomotion(self, packet: bytes) -> bool:
            sent.append(packet)
            return True

    sonic = SonicClient(gateway=Gw())
    asyncio.run(sonic.halt_control())

    kill = build_command_message(start=False, stop=True, planner=True)
    assert kill not in sent
    # Must keep start=True, stop=False so G1Deploy stays alive.
    keep = build_command_message(start=True, stop=False, planner=True)
    assert keep in sent


def test_live_default_detector_is_not_demo() -> None:
    cfg = RuntimeConfig()
    assert isinstance(_default_detector(cfg, live=False), DemoDetector)
    assert isinstance(_default_detector(cfg, live=True), LiveTimeoutDetector)
