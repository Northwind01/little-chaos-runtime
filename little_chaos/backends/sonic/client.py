"""Thin ZMQ publisher for SONIC planner/command messages."""

from __future__ import annotations

import time
from typing import Any, Callable

from little_chaos.backends.sonic.locomotion import (
    PlannerCommand,
    idle_command,
    retreat_command,
    turn_command,
    walk_command,
)
from little_chaos.backends.sonic.protocol import build_command_message, build_planner_message
from little_chaos.runtime.ownership import ControlOwnershipError

SendFn = Callable[[bytes], None]


class SonicClient:
    """Higher layers call walk/stop/retreat/turn_around, never raw ZMQ.

    Live autonomous sessions pass packets through SonicCommandGateway
    (`submit_locomotion`). Command/start-stop packets used for mode
    transitions should go through `gateway.publish_control` from the runtime.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5556,
        send: SendFn | None = None,
        bind: bool = False,
        gateway: Any | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self._gateway = gateway
        if gateway is not None and send is None:
            send = gateway.submit_locomotion
        self._send = send
        self._bind = bind
        self._socket: Any = None
        self._ctx: Any = None
        self.last_command: PlannerCommand | None = None
        self.last_control: dict[str, bool] | None = None
        self.ready = send is not None or gateway is not None

    def connect(self) -> None:
        if self._gateway is not None:
            self.ready = True
            return
        if self._send is not None:
            self.ready = True
            return
        try:
            import zmq
        except ImportError as exc:
            raise RuntimeError("pyzmq is required for live SONIC control") from exc
        self._ctx = zmq.Context.instance()
        socket = self._ctx.socket(zmq.PUB)
        endpoint = f"tcp://{self.host}:{self.port}"
        try:
            if self._bind:
                socket.bind(endpoint)
            else:
                socket.connect(endpoint)
        except Exception as exc:
            socket.close(0)
            raise ControlOwnershipError(
                f"cannot publish SONIC commands on {endpoint}: {exc}"
            ) from exc
        time.sleep(0.05)
        self._socket = socket
        self.ready = True

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close(0)
            self._socket = None
        self.ready = False

    def send_command(self, *, start: bool, stop: bool, planner: bool = True) -> bytes:
        packet = build_command_message(start=start, stop=stop, planner=planner)
        self.last_control = {"start": start, "stop": stop, "planner": planner}
        if self._gateway is not None:
            self._gateway.publish_control(packet)
        else:
            self._publish(packet)
        return packet

    def send_planner(self, command: PlannerCommand) -> bytes:
        packet = build_planner_message(
            command.mode,
            command.movement,
            command.facing,
            speed=command.speed,
            height=command.height,
        )
        self.last_command = command
        self._publish(packet)
        return packet

    async def walk(self, direction: str, speed: str, yaw: float) -> PlannerCommand:
        command = walk_command(direction, speed, yaw)
        self.send_planner(command)
        return command

    async def stop(self, yaw: float | None = None) -> PlannerCommand:
        command = idle_command(yaw)
        self.send_planner(command)
        return command

    async def retreat(self, yaw: float) -> PlannerCommand:
        command = retreat_command(yaw)
        self.send_planner(command)
        return command

    async def turn_around(self, target_yaw: float) -> PlannerCommand:
        command = turn_command(target_yaw)
        self.send_planner(command)
        return command

    async def enable_planner(self) -> None:
        """Start (or keep) the C++ control loop in PLANNER mode."""
        self.send_command(start=True, stop=False, planner=True)

    async def enable_pose(self) -> None:
        """Start (or keep) the C++ control loop in POSE / streamed-motion mode."""
        self.send_command(start=True, stop=False, planner=False)

    async def publish_idle(self, yaw: float | None = None) -> PlannerCommand:
        """Always-forwarded IDLE planner packet (works even when gateway source is NONE)."""
        command = idle_command(yaw)
        packet = build_planner_message(
            command.mode,
            command.movement,
            command.facing,
            speed=command.speed,
            height=command.height,
        )
        self.last_command = command
        if self._gateway is not None:
            self._gateway.publish_control(packet)
        else:
            self._publish(packet)
        return command

    async def halt_control(self) -> None:
        """Safe episode idle. Keeps G1Deploy alive.

        Never send ``stop=True``: SONIC maps that to ``operator_state.stop`` and
        the whole ``deploy.sh`` / G1Deploy process exits.
        """
        await self.publish_idle()
        # Stay in planner mode with control still started (idle motion only).
        self.send_command(start=True, stop=False, planner=True)

    async def shutdown_control(self) -> None:
        """Operator kill of G1Deploy. Prefer tearing down the session instead."""
        self.send_command(start=False, stop=True, planner=True)

    def _publish(self, packet: bytes) -> None:
        if self._send is not None:
            self._send(packet)
            return
        if self._socket is None:
            raise RuntimeError("SonicClient.connect() was not called")
        self._socket.send(packet)
