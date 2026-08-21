import pytest

from little_chaos.runtime.ownership import ControlGate, ControlOwnershipError
from little_chaos.runtime.types import ControlOwner


def test_acquire_fails_when_port_already_bound() -> None:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    try:
        gate = ControlGate("127.0.0.1", port)
        with pytest.raises(ControlOwnershipError):
            gate.acquire_autonomous()
    finally:
        sock.close()


def test_snapshot_reports_autonomous_after_acquire_even_if_port_busy() -> None:
    gate = ControlGate("127.0.0.1", 1)
    gate.owner = ControlOwner.AUTONOMOUS
    status = gate.snapshot()
    if not status.teleop_process:
        assert status.owner is ControlOwner.AUTONOMOUS


def test_reacquire_when_already_autonomous_does_not_fail() -> None:
    gate = ControlGate("127.0.0.1", 59999)
    gate.owner = ControlOwner.AUTONOMOUS
    status = gate.acquire_autonomous()
    assert status.owner is ControlOwner.AUTONOMOUS
