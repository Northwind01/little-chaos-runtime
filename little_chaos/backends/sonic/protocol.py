"""SONIC planner ZMQ packet builders.

Prefers the upstream helpers from gear_sonic. Falls back to a local copy of
the same wire format so tests can run without the WBC checkout.
"""

from __future__ import annotations

import json
import struct
from typing import Sequence

HEADER_SIZE = 1280


def _build_header(fields: list, version: int = 1, count: int = 1) -> bytes:
    header = {
        "v": version,
        "endian": "le",
        "count": count,
        "fields": fields,
    }
    header_json = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if len(header_json) > HEADER_SIZE:
        raise ValueError(f"Header too large: {len(header_json)} > {HEADER_SIZE}")
    return header_json.ljust(HEADER_SIZE, b"\x00")


def _local_build_command_message(
    start: bool, stop: bool, planner: bool, delta_heading: float | None = None
) -> bytes:
    fields = [
        {"name": "start", "dtype": "u8", "shape": [1]},
        {"name": "stop", "dtype": "u8", "shape": [1]},
        {"name": "planner", "dtype": "u8", "shape": [1]},
    ]
    payload = b"".join(
        (
            struct.pack("B", 1 if start else 0),
            struct.pack("B", 1 if stop else 0),
            struct.pack("B", 1 if planner else 0),
        )
    )
    if delta_heading is not None:
        fields.append({"name": "delta_heading", "dtype": "f32", "shape": [1]})
        payload += struct.pack("<f", float(delta_heading))
    return b"command" + _build_header(fields) + payload


def _local_build_planner_message(
    mode: int,
    movement: Sequence[float],
    facing: Sequence[float],
    speed: float = -1.0,
    height: float = -1.0,
) -> bytes:
    if len(movement) != 3:
        raise ValueError("movement must have length 3")
    if len(facing) != 3:
        raise ValueError("facing must have length 3")
    fields = [
        {"name": "mode", "dtype": "i32", "shape": [1]},
        {"name": "movement", "dtype": "f32", "shape": [3]},
        {"name": "facing", "dtype": "f32", "shape": [3]},
        {"name": "speed", "dtype": "f32", "shape": [1]},
        {"name": "height", "dtype": "f32", "shape": [1]},
    ]
    payload = b"".join(
        (
            struct.pack("<i", int(mode)),
            struct.pack("<fff", float(movement[0]), float(movement[1]), float(movement[2])),
            struct.pack("<fff", float(facing[0]), float(facing[1]), float(facing[2])),
            struct.pack("<f", float(speed)),
            struct.pack("<f", float(height)),
        )
    )
    return b"planner" + _build_header(fields) + payload


def _load_upstream():
    try:
        from gear_sonic.utils.teleop.zmq.zmq_planner_sender import (
            build_command_message as upstream_command,
        )
        from gear_sonic.utils.teleop.zmq.zmq_planner_sender import (
            build_planner_message as upstream_planner,
        )
    except ImportError:
        return None
    return upstream_command, upstream_planner


_UPSTREAM = _load_upstream()
if _UPSTREAM is not None:
    build_command_message = _UPSTREAM[0]
    build_planner_message = _UPSTREAM[1]
else:
    build_command_message = _local_build_command_message
    build_planner_message = _local_build_planner_message
