"""JSONL task telemetry. Separate from LeRobot training data."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class TaskLogger:
    def __init__(self, log_dir: str | os.PathLike[str] = "logs/runtime") -> None:
        self.log_dir = Path(log_dir)
        self.path: Path | None = None
        self._fh = None

    def open_task(self, task_id: str) -> Path:
        self.close()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{task_id}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")
        return self.path

    def emit(self, event: str, **payload: Any) -> None:
        record = {
            "ts": time.time(),
            "event": event,
            **payload,
        }
        line = json.dumps(record, default=_json_default, sort_keys=True)
        if self._fh is not None:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def _json_default(value: Any) -> Any:
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        try:
            return value.value
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return str(value)
