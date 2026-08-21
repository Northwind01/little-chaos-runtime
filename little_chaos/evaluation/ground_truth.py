"""Privileged MuJoCo observer. Does not replace VLM semantic decisions."""

from __future__ import annotations

from little_chaos.evaluation.types import GroundTruthReport
from little_chaos.runtime.types import PrivilegedSnapshot
from little_chaos.world.observation import WorldState


class GroundTruthEvaluator:
    def __init__(self, world: WorldState) -> None:
        self.world = world

    def observe(self) -> GroundTruthReport:
        snapshot = self.world.snapshot()
        notes = {
            "girl_distance": snapshot.robot_girl_distance,
            "collision": snapshot.collision,
            "upright": snapshot.upright,
            "fallen": snapshot.fallen,
            "yaw": snapshot.yaw,
            "girl_visible": snapshot.girl_visible,
        }
        return GroundTruthReport(snapshot=snapshot, notes=notes)

    @staticmethod
    def format_log(snapshot: PrivilegedSnapshot) -> str:
        dist = snapshot.robot_girl_distance
        dist_s = "n/a" if dist is None else f"{dist:.2f}"
        return (
            f"MuJoCo: girl_distance={dist_s} collision={str(snapshot.collision).lower()} "
            f"upright={str(snapshot.upright).lower()} fallen={str(snapshot.fallen).lower()}"
        )
