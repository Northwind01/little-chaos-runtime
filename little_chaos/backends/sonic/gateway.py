"""Single autonomous binder of SONIC command port :5556.

Transport multiplexing and source filtering only. Not a planner.
PICO teleop does not go through this gateway.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from little_chaos.runtime.ownership import ControlOwnershipError
from little_chaos.runtime.types import CommandSource

ForwardFn = Callable[[bytes], None]


class SonicCommandGateway:
    """PUB-bind :5556; accept packed pose/planner/command from GROOT or locomotion."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        sonic_port: int = 5556,
        groot_ingest_host: str = "127.0.0.1",
        groot_ingest_port: int = 5561,
        forward: ForwardFn | None = None,
    ) -> None:
        self.host = host
        self.sonic_port = int(sonic_port)
        self.groot_ingest_host = groot_ingest_host
        self.groot_ingest_port = int(groot_ingest_port)
        self._external_forward = forward

        self.active_source = CommandSource.NONE
        self.generation = 0
        self.forwarded = 0
        self.dropped = 0
        self.control_sent = 0
        self.bound = False

        self._lock = threading.Lock()
        self._ctx = None
        self._pub = None
        self._ingest = None
        self._ingest_thread: threading.Thread | None = None
        self._stop = threading.Event()

    def bind(self) -> None:
        """Bind the SONIC PUB socket. Call only after ControlGate.acquire_autonomous()."""
        if self._external_forward is not None and self._pub is None:
            # Tests / offline: no ZMQ, still mark ready so ingest thread is optional.
            self.bound = True
            return
        try:
            import zmq
        except ImportError as exc:
            raise RuntimeError("pyzmq is required for the live SONIC command gateway") from exc

        self._ctx = zmq.Context.instance()
        pub = self._ctx.socket(zmq.PUB)
        endpoint = f"tcp://{self.host}:{self.sonic_port}"
        try:
            pub.bind(endpoint)
        except Exception as exc:
            pub.close(0)
            raise ControlOwnershipError(
                f"cannot bind SONIC command gateway on {endpoint}: {exc}. "
                "Stop pico_manager / bind-mode inference before starting the autonomous runtime."
            ) from exc

        ingest = self._ctx.socket(zmq.SUB)
        ingest.setsockopt_string(zmq.SUBSCRIBE, "")
        ingest.setsockopt(zmq.RCVTIMEO, 100)
        ingest_ep = f"tcp://{self.groot_ingest_host}:{self.groot_ingest_port}"
        try:
            ingest.bind(ingest_ep)
        except Exception as exc:
            pub.close(0)
            ingest.close(0)
            raise ControlOwnershipError(
                f"cannot bind GROOT ingest on {ingest_ep}: {exc}"
            ) from exc

        time.sleep(0.05)
        self._pub = pub
        self._ingest = ingest
        self.bound = True
        self._stop.clear()
        self._ingest_thread = threading.Thread(
            target=self._ingest_loop,
            name="sonic-groot-ingest",
            daemon=True,
        )
        self._ingest_thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._ingest_thread is not None:
            self._ingest_thread.join(timeout=1.0)
            self._ingest_thread = None
        if self._ingest is not None:
            self._ingest.close(0)
            self._ingest = None
        if self._pub is not None:
            self._pub.close(0)
            self._pub = None
        self.bound = False
        with self._lock:
            self.active_source = CommandSource.NONE

    def set_active_source(self, source: CommandSource) -> int:
        with self._lock:
            self.active_source = source
            self.generation += 1
            return self.generation

    def submit(self, source: CommandSource, packet: bytes, generation: int | None = None) -> bool:
        """Forward a producer packet only if `source` is currently active."""
        with self._lock:
            if source is CommandSource.NONE or source is not self.active_source:
                self.dropped += 1
                return False
            if generation is not None and generation != self.generation:
                self.dropped += 1
                return False
            self._forward_locked(packet)
            self.forwarded += 1
            return True

    def submit_locomotion(self, packet: bytes) -> bool:
        return self.submit(CommandSource.LOCOMOTION, packet)

    def submit_groot(self, packet: bytes) -> bool:
        return self.submit(CommandSource.GROOT, packet)

    def publish_control(self, packet: bytes) -> None:
        """Runtime-only idle/mode packets. Always forwarded, even when source is NONE."""
        with self._lock:
            self._forward_locked(packet)
            self.control_sent += 1

    def _forward_locked(self, packet: bytes) -> None:
        if self._external_forward is not None:
            self._external_forward(packet)
        if self._pub is not None:
            self._pub.send(packet)

    def _ingest_loop(self) -> None:
        ingest = self._ingest
        if ingest is None:
            return
        while not self._stop.is_set():
            try:
                packet = ingest.recv()
            except Exception:
                continue
            if not packet:
                continue
            self.submit_groot(packet)
