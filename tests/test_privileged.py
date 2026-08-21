import pytest

from little_chaos.runtime.types import PrivilegedSnapshot
from little_chaos.world.privileged import parse_privileged_payload


def test_parse_privileged_payload() -> None:
    snap = parse_privileged_payload(
        {
            "robot_xy": [1.0, 2.0],
            "robot_xyz": [1.0, 2.0, 0.8],
            "yaw": 0.3,
            "girl_xy": [3.0, 4.0],
            "robot_girl_distance": 2.8,
            "collision": False,
            "fallen": False,
            "upright": True,
            "girl_visible": True,
        }
    )
    assert isinstance(snap, PrivilegedSnapshot)
    assert snap.robot_xy == (1.0, 2.0)
    assert snap.girl_xy == (3.0, 4.0)
    assert snap.robot_girl_distance == pytest.approx(2.8)
    assert snap.collision is False
    assert snap.upright is True
    assert snap.girl_visible is True
    assert snap.yaw == pytest.approx(0.3)


def test_parse_privileged_json_string() -> None:
    snap = parse_privileged_payload(
        '{"robot_xy":[0,1],"collision":true,"fallen":false,"upright":true}'
    )
    assert snap.robot_xy == (0.0, 1.0)
    assert snap.collision is True
