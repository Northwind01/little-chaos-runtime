"""World observation adapters. Never issue robot commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from little_chaos.runtime.types import PrivilegedSnapshot


class WorldState(Protocol):
    def snapshot(self) -> PrivilegedSnapshot:
        ...

    def ego_rgb(self) -> Any:
        ...

    def safety_veto(self) -> str | None:
        ...


@dataclass
class BasePose:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0


@dataclass
class StaticWorld:
    pose: BasePose = field(default_factory=BasePose)
    privileged: PrivilegedSnapshot = field(default_factory=PrivilegedSnapshot)
    frame: Any = None
    veto: str | None = None

    def snapshot(self) -> PrivilegedSnapshot:
        snap = PrivilegedSnapshot(
            robot_xy=(self.pose.x, self.pose.y),
            robot_xyz=(self.pose.x, self.pose.y, self.pose.z),
            girl_xy=self.privileged.girl_xy,
            robot_girl_distance=self.privileged.robot_girl_distance,
            girl_visible=self.privileged.girl_visible,
            collision=self.privileged.collision,
            upright=self.privileged.upright,
            fallen=self.privileged.fallen,
            yaw=self.pose.yaw,
        )
        if snap.girl_xy is not None and snap.robot_girl_distance is None:
            dx = snap.girl_xy[0] - self.pose.x
            dy = snap.girl_xy[1] - self.pose.y
            snap.robot_girl_distance = (dx * dx + dy * dy) ** 0.5
        return snap

    def ego_rgb(self) -> Any:
        return self.frame

    def safety_veto(self) -> str | None:
        if self.veto:
            return self.veto
        snap = self.snapshot()
        if snap.collision:
            return "collision INVALID"
        if snap.fallen or not snap.upright:
            return "robot fallen"
        return None


class EgoRgbSource:
    """Latest-frame adapter around vr_camera_bridge when the lab is on PYTHONPATH."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5555,
        camera_name: str = "ego_view",
        color_order: str = "rgb",
    ) -> None:
        self.host = host
        self.port = int(port)
        self.camera_name = camera_name
        self.color_order = color_order
        self._source = None
        self.last_frame = None
        self.ready = False

    def connect(self) -> None:
        try:
            from vr_camera_bridge.ego_frame_source import GrootEgoFrameSource
        except ImportError as exc:
            raise RuntimeError(
                "vr_camera_bridge is not importable. Set PYTHONPATH to the "
                "gr00t-wbc-lab repo (and src/) for live ego RGB."
            ) from exc
        source = GrootEgoFrameSource(
            host=self.host,
            port=self.port,
            camera_name=self.camera_name,
            color_order=self.color_order,
        )
        source.start()
        self._source = source
        self.ready = True

    def ego_rgb(self) -> Any:
        if self._source is None:
            return self.last_frame
        frame = self._source.get_latest_frame()
        if frame is not None:
            self.last_frame = getattr(frame, "image", frame)
        return self.last_frame

    def close(self) -> None:
        if self._source is not None:
            self._source.close()
            self._source = None
        self.ready = False
