"""SONIC command gateway: source filtering and control bypass."""

from little_chaos.backends.sonic.gateway import SonicCommandGateway
from little_chaos.runtime.types import CommandSource


def test_gateway_forwards_only_active_source() -> None:
    sent: list[bytes] = []
    gw = SonicCommandGateway(forward=sent.append)
    gw.bind()
    gw.set_active_source(CommandSource.LOCOMOTION)
    assert gw.submit_locomotion(b"walk") is True
    assert gw.submit_groot(b"pose") is False
    assert sent == [b"walk"]
    gw.set_active_source(CommandSource.GROOT)
    assert gw.submit_groot(b"pose") is True
    assert gw.submit_locomotion(b"walk2") is False
    assert sent == [b"walk", b"pose"]


def test_gateway_publish_control_bypasses_source() -> None:
    sent: list[bytes] = []
    gw = SonicCommandGateway(forward=sent.append)
    gw.set_active_source(CommandSource.NONE)
    gw.publish_control(b"idle")
    assert sent == [b"idle"]
    assert gw.control_sent == 1
    assert gw.submit_locomotion(b"walk") is False
    assert gw.dropped >= 1


def test_generation_drops_stale_in_process_submit() -> None:
    sent: list[bytes] = []
    gw = SonicCommandGateway(forward=sent.append)
    gen = gw.set_active_source(CommandSource.LOCOMOTION)
    assert gw.submit(CommandSource.LOCOMOTION, b"a", generation=gen) is True
    gw.set_active_source(CommandSource.LOCOMOTION)
    assert gw.submit(CommandSource.LOCOMOTION, b"stale", generation=gen) is False
    assert b"stale" not in sent
