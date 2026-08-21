"""Privileged observational state from the sim PUB on :5559."""

from __future__ import annotations

import json
from typing import Any

from little_chaos.runtime.types import PrivilegedSnapshot


def parse_privileged_payload(payload: Any) -> PrivilegedSnapshot:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("privileged payload must be a JSON object")

    def _xy(value: Any) -> tuple[float, float] | None:
        if value is None:
            return None
        return (float(value[0]), float(value[1]))

    def _xyz(value: Any) -> tuple[float, float, float] | None:
        if value is None:
            return None
        return (float(value[0]), float(value[1]), float(value[2]))

    dist = payload.get("robot_girl_distance")
    yaw = payload.get("yaw")
    visible = payload.get("girl_visible")
    return PrivilegedSnapshot(
        robot_xy=_xy(payload.get("robot_xy")),
        robot_xyz=_xyz(payload.get("robot_xyz")),
        girl_xy=_xy(payload.get("girl_xy")),
        robot_girl_distance=None if dist is None else float(dist),
        girl_visible=None if visible is None else bool(visible),
        collision=bool(payload.get("collision", False)),
        upright=bool(payload.get("upright", True)),
        fallen=bool(payload.get("fallen", False)),
        yaw=None if yaw is None else float(yaw),
    )


class PrivilegedStateSource:
    """SUB-connect to the sim privileged publisher. Never sends robot commands."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5559) -> None:
        self.host = host
        self.port = int(port)
        self._sub = None
        self._ctx = None
        self.last: PrivilegedSnapshot | None = None
        self.ready = False

    def connect(self) -> None:
        try:
            import zmq
        except ImportError as exc:
            raise RuntimeError("pyzmq is required for live privileged state") from exc
        self._ctx = zmq.Context.instance()
        sock = self._ctx.socket(zmq.SUB)
        sock.setsockopt_string(zmq.SUBSCRIBE, "")
        sock.setsockopt(zmq.CONFLATE, 1)
        sock.setsockopt(zmq.RCVTIMEO, 0)
        sock.connect(f"tcp://{self.host}:{self.port}")
        self._sub = sock
        self.ready = True

    def snapshot(self) -> PrivilegedSnapshot:
        self._poll()
        return self.last or PrivilegedSnapshot()

    def ego_rgb(self) -> Any:
        return None

    def safety_veto(self) -> str | None:
        snap = self.snapshot()
        if snap.collision:
            return "collision INVALID"
        if snap.fallen or not snap.upright:
            return "robot fallen"
        return None

    def _poll(self) -> None:
        if self._sub is None:
            return
        try:
            raw = self._sub.recv()
        except Exception:
            return
        if not raw:
            return
        try:
            self.last = parse_privileged_payload(raw)
        except Exception:
            return

    def close(self) -> None:
        if self._sub is not None:
            self._sub.close(0)
            self._sub = None
        self.ready = False
