"""Adapter around the existing GR00T inference control path.

The live client does not reimplement PolicyServer math. It drives the host
VLA process already launched by `make inference` through the keyboard ZMQ
channel (`prompt:`, `p` pause/resume).

Autonomous sessions PUB-bind :5580 (do not start keyboard.sh). Packed pose
tokens still leave `run_vla_inference` and enter SonicCommandGateway ingest.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable

SendFn = Callable[[str], None]


class GrootClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5580,
        send: SendFn | None = None,
        bind: bool = True,
    ) -> None:
        self.host = host
        self.port = int(port)
        self._send = send
        self._bind = bind
        self._socket = None
        self._ctx = None
        self._running = False
        self._bootstrapped = False
        self.current_instruction: str | None = None
        self.ready = send is not None

    def connect(self) -> None:
        if self._send is not None:
            self.ready = True
            return
        try:
            import zmq
        except ImportError as exc:
            raise RuntimeError("pyzmq is required for live GR00T control") from exc
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
            raise RuntimeError(
                f"cannot open GR00T keyboard socket {endpoint}: {exc}. "
                "For autonomous sessions bind :5580 and do not start keyboard.sh."
            ) from exc
        time.sleep(0.05)
        self._socket = socket
        self.ready = True

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close(0)
            self._socket = None
        self.ready = False
        self._running = False

    async def bootstrap_control(self) -> None:
        """Prepare inference for the first VLA skill.

        C++ loop start is owned by ``SonicClient.enable_pose()`` (runtime
        ``publish_control``). Here we only send keyboard ``i`` (initial pose +
        POSE mode) so we do not toggle the deploy with a redundant ``k``.
        """
        if self._bootstrapped:
            return
        # Slow-joiner: give inference's SUB a moment if it just connected.
        await asyncio.sleep(0.5)
        self.publish("i")
        await asyncio.sleep(2.0)
        self._bootstrapped = True

    async def start_skill(self, instruction: str) -> None:
        text = instruction.strip()
        if not text:
            raise ValueError("GR00T instruction must be a non-empty canonical string")
        await self.bootstrap_control()
        self.publish(f"prompt:{text}")
        if not self._running:
            self.publish("p")
        self._running = True
        self.current_instruction = text

    async def cancel(self) -> None:
        if self._running:
            self.publish("p")
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def publish(self, message: str) -> None:
        if self._send is not None:
            self._send(message)
            return
        if self._socket is None:
            raise RuntimeError("GrootClient.connect() was not called")
        self._socket.send_string(message)
