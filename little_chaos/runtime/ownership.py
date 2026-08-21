"""Process-level SONIC command ownership.

Teleop (`pico_manager_thread_server.py`) binds ZMQ PUB on :5556.
Autonomous sessions bind that port via SonicCommandGateway instead.
The two modes must never share the socket.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass

from little_chaos.runtime.types import ControlOwner

_TELEOP_PROCESS_MARKERS = (
    "pico_manager_thread_server.py",
    "pico_manager_thread_server",
)


class ControlOwnershipError(RuntimeError):
    pass


@dataclass
class OwnershipStatus:
    owner: ControlOwner
    reason: str
    port_in_use: bool = False
    teleop_process: bool = False


def _port_in_use(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((host, int(port))) == 0
    finally:
        sock.close()


def _teleop_process_running() -> bool:
    proc = "/proc"
    if not os.path.isdir(proc):
        return False
    try:
        pids = os.listdir(proc)
    except OSError:
        return False
    for pid in pids:
        if not pid.isdigit():
            continue
        cmdline_path = os.path.join(proc, pid, "cmdline")
        try:
            raw = open(cmdline_path, "rb").read()
        except OSError:
            continue
        text = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
        if any(marker in text for marker in _TELEOP_PROCESS_MARKERS):
            return True
    return False


def inspect_ownership(host: str = "127.0.0.1", port: int = 5556) -> OwnershipStatus:
    teleop = _teleop_process_running()
    busy = _port_in_use(host, port)
    if teleop:
        return OwnershipStatus(
            owner=ControlOwner.TELEOP,
            reason="pico_manager_thread_server.py is running; teleop owns SONIC :5556",
            port_in_use=busy,
            teleop_process=True,
        )
    if busy:
        return OwnershipStatus(
            owner=ControlOwner.TELEOP,
            reason=(
                f"tcp://{host}:{port} is already bound. Stop pico_manager or "
                "bind-mode GR00T inference before starting the autonomous runtime."
            ),
            port_in_use=True,
            teleop_process=False,
        )
    return OwnershipStatus(
        owner=ControlOwner.IDLE,
        reason="SONIC command port is free",
        port_in_use=False,
        teleop_process=False,
    )


class ControlGate:
    """Single-process ownership flag used by the execution runtime."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5556) -> None:
        self.host = host
        self.port = int(port)
        self.owner = ControlOwner.IDLE
        self.last_status: OwnershipStatus | None = None

    def snapshot(self) -> OwnershipStatus:
        status = inspect_ownership(self.host, self.port)
        if self.owner is ControlOwner.AUTONOMOUS and not status.teleop_process:
            status = OwnershipStatus(
                owner=ControlOwner.AUTONOMOUS,
                reason="autonomous runtime holds command ownership",
                port_in_use=status.port_in_use,
                teleop_process=False,
            )
        self.last_status = status
        return status

    def acquire_autonomous(self) -> OwnershipStatus:
        if self.owner is ControlOwner.AUTONOMOUS:
            status = OwnershipStatus(
                owner=ControlOwner.AUTONOMOUS,
                reason="autonomous ownership already held",
                port_in_use=True,
                teleop_process=False,
            )
            self.last_status = status
            return status
        status = inspect_ownership(self.host, self.port)
        self.last_status = status
        if status.owner is ControlOwner.TELEOP or status.port_in_use or status.teleop_process:
            raise ControlOwnershipError(status.reason)
        self.owner = ControlOwner.AUTONOMOUS
        return OwnershipStatus(
            owner=ControlOwner.AUTONOMOUS,
            reason="acquired autonomous ownership",
            port_in_use=False,
            teleop_process=False,
        )

    def release(self) -> None:
        self.owner = ControlOwner.IDLE
