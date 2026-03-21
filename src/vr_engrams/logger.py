from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ExperimentLogger:
    """Structured event logger with parameter snapshot support."""

    root_dir: Path
    animal_id: str
    config: dict[str, Any]
    run_name: str = "run"
    _start_time: float = field(default_factory=time.perf_counter, init=False)
    _event_file: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_dir = self.root_dir / self.animal_id / f"{self.run_name}_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._event_path = self.session_dir / "events.jsonl"
        self._event_file = self._event_path.open("w", encoding="utf-8")
        self.snapshot_parameters()

    def snapshot_parameters(self) -> None:
        snapshot_path = self.session_dir / "parameters_snapshot.yaml"
        with snapshot_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config, handle, sort_keys=False)

    def log_event(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_sec": round(time.perf_counter() - self._start_time, 6),
            "animal_id": self.animal_id,
            "event": event,
            "fields": fields,
        }
        self._event_file.write(json.dumps(record) + "\n")
        self._event_file.flush()

    def close(self) -> None:
        if self._event_file and not self._event_file.closed:
            self._event_file.close()
