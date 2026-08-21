"""Privileged robot/girl state from MuJoCo or the SONIC g1_debug stream."""

from __future__ import annotations

import math
from typing import Any

from little_chaos.backends.sonic.locomotion import wrap_yaw
from little_chaos.runtime.types import PrivilegedSnapshot
from little_chaos.world.observation import BasePose, StaticWorld


def yaw_from_quat_wxyz(quat: Any) -> float:
    qw, qx, qy, qz = (float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return wrap_yaw(math.atan2(siny_cosp, cosy_cosp))


def pose_from_state_msg(msg: dict[str, Any]) -> BasePose:
    pose = BasePose()
    if "base_quat" in msg:
        pose.yaw = yaw_from_quat_wxyz(msg["base_quat"])
    for key in ("base_pos", "root_pos", "position", "floating_base_pose"):
        if key not in msg:
            continue
        arr = msg[key]
        pose.x = float(arr[0])
        pose.y = float(arr[1])
        if len(arr) > 2 and key != "floating_base_pose":
            pose.z = float(arr[2])
        if key == "floating_base_pose" and len(arr) >= 7:
            pose.z = float(arr[2])
            pose.yaw = yaw_from_quat_wxyz(arr[3:7])
        break
    return pose


class ZmqRobotState:
    """Subscribe to SONIC `g1_debug` on :5557 when gear_sonic is available."""

    def __init__(self, host: str = "localhost", port: int = 5557) -> None:
        self.host = host
        self.port = int(port)
        self._sub = None
        self.last_msg: dict[str, Any] | None = None
        self.ready = False

    def connect(self) -> None:
        try:
            from gear_sonic.utils.data_collection.zmq_state_subscriber import ZMQStateSubscriber
        except ImportError as exc:
            raise RuntimeError(
                "gear_sonic is not importable. Set PYTHONPATH to "
                "GR00T-WholeBodyControl for live robot state."
            ) from exc
        self._sub = ZMQStateSubscriber(host=self.host, port=self.port)
        self.ready = True

    def pose(self) -> BasePose:
        msg = self._read()
        if msg is None:
            return BasePose()
        return pose_from_state_msg(msg)

    def snapshot(self) -> PrivilegedSnapshot:
        pose = self.pose()
        fallen = pose.z != 0.0 and pose.z < 0.2
        return PrivilegedSnapshot(
            robot_xy=(pose.x, pose.y),
            robot_xyz=(pose.x, pose.y, pose.z),
            yaw=pose.yaw,
            fallen=fallen,
            upright=not fallen,
        )

    def ego_rgb(self) -> Any:
        return None

    def safety_veto(self) -> str | None:
        snap = self.snapshot()
        if snap.fallen:
            return "robot fallen"
        return None

    def _read(self) -> dict[str, Any] | None:
        if self._sub is None:
            return self.last_msg
        msg = self._sub.get_msg(clear=False)
        if msg is not None:
            self.last_msg = msg
        return self.last_msg

    def close(self) -> None:
        if self._sub is not None:
            self._sub.close()
            self._sub = None
        self.ready = False


class MujocoWorld:
    """Observational privileged state from live mj_model / mj_data."""

    def __init__(self, model: Any, data: Any, collision_supervisor: Any = None) -> None:
        self.model = model
        self.data = data
        self.collision_supervisor = collision_supervisor
        self.frame = None

    def snapshot(self) -> PrivilegedSnapshot:
        try:
            from littlechaos_eval.mujoco_access import body_position, xy_distance
        except ImportError:
            qpos = getattr(self.data, "qpos", None)
            yaw = 0.0
            xy = (0.0, 0.0)
            z = 1.0
            if qpos is not None and len(qpos) >= 7:
                xy = (float(qpos[0]), float(qpos[1]))
                z = float(qpos[2])
                yaw = yaw_from_quat_wxyz(qpos[3:7])
            fallen = z < 0.2
            collision = False
            if self.collision_supervisor is not None:
                collision = not bool(getattr(self.collision_supervisor, "episode_valid", True))
            return PrivilegedSnapshot(
                robot_xy=xy,
                robot_xyz=(xy[0], xy[1], z),
                yaw=yaw,
                fallen=fallen,
                upright=not fallen,
                collision=collision,
            )

        robot = body_position(self.model, self.data, "pelvis")
        girl_xy = None
        dist = None
        visible = None
        try:
            girl = body_position(self.model, self.data, "girl_actor")
            girl_xy = (float(girl[0]), float(girl[1]))
            dist = xy_distance(robot, girl)
        except Exception:
            girl = None
        try:
            from littlechaos_eval.visibility import GirlVisibility

            vis = GirlVisibility(self.model)
            visible = bool(vis.evaluate(self.data).girl_visible)
        except Exception:
            visible = None
        yaw = 0.0
        upright = True
        if hasattr(self.data, "xmat"):
            try:
                from littlechaos_eval.mujoco_access import body_id

                bid = body_id(self.model, "pelvis")
                R = self.data.xmat[bid].reshape(3, 3)
                upright = float(R[2, 2]) >= 0.85
                yaw = math.atan2(float(R[1, 0]), float(R[0, 0]))
            except Exception:
                pass
        collision = False
        if self.collision_supervisor is not None:
            collision = not bool(getattr(self.collision_supervisor, "episode_valid", True))
        z = float(robot[2])
        fallen = z < 0.2 or not upright
        return PrivilegedSnapshot(
            robot_xy=(float(robot[0]), float(robot[1])),
            robot_xyz=(float(robot[0]), float(robot[1]), z),
            girl_xy=girl_xy,
            robot_girl_distance=dist,
            girl_visible=visible,
            collision=collision,
            upright=upright,
            fallen=fallen,
            yaw=wrap_yaw(yaw),
        )

    def ego_rgb(self) -> Any:
        return self.frame

    def safety_veto(self) -> str | None:
        snap = self.snapshot()
        if snap.collision:
            return "collision INVALID"
        if snap.fallen:
            return "robot fallen"
        return None


class CompositeWorld:
    """Combine ego RGB + robot/privileged state sources."""

    def __init__(self, rgb_source: Any | None = None, state_source: Any | None = None) -> None:
        self.rgb_source = rgb_source
        self.state_source = state_source or StaticWorld()

    def snapshot(self) -> PrivilegedSnapshot:
        return self.state_source.snapshot()

    def ego_rgb(self) -> Any:
        if self.rgb_source is not None:
            return self.rgb_source.ego_rgb()
        return getattr(self.state_source, "ego_rgb", lambda: None)()

    def safety_veto(self) -> str | None:
        return self.state_source.safety_veto()
