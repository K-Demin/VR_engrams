from __future__ import annotations

import json
import time
import csv
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
    console_echo: bool = True
    _start_time: float = field(default_factory=time.perf_counter, init=False)
    _event_file: Any = field(default=None, init=False)
    _event_csv_file: Any = field(default=None, init=False)
    _event_csv_writer: Any = field(default=None, init=False)
    _behavior_file: Any = field(default=None, init=False)
    _behavior_writer: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_dir = self.root_dir / self.animal_id / f"{self.run_name}_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._event_path = self.session_dir / "events.jsonl"
        self._event_file = self._event_path.open("w", encoding="utf-8")

        self._event_csv_path = self.session_dir / "events.csv"
        self._event_csv_file = self._event_csv_path.open("w", encoding="utf-8", newline="")
        self._event_csv_writer = csv.writer(self._event_csv_file)
        self._event_csv_writer.writerow(["timestamp_utc", "elapsed_sec", "animal_id", "event", "fields_json"])

        self._behavior_path = self.session_dir / "behavior_log.csv"
        self._behavior_file = self._behavior_path.open("w", encoding="utf-8", newline="")
        self._behavior_writer = csv.writer(self._behavior_file)
        self._behavior_writer.writerow(["timestamp_sec", "event", "trial", "phase", "detail"])

        self.snapshot_parameters()

    def snapshot_parameters(self) -> None:
        snapshot_path = self.session_dir / "parameters_snapshot.yaml"
        with snapshot_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config, handle, sort_keys=False)

    def log_event(self, event: str, **fields: Any) -> None:
        elapsed_sec = round(time.perf_counter() - self._start_time, 6)
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_sec": elapsed_sec,
            "animal_id": self.animal_id,
            "event": event,
            "fields": fields,
        }
        self._event_file.write(json.dumps(record) + "\n")
        self._event_file.flush()
        self._event_csv_writer.writerow(
            [
                record["timestamp_utc"],
                record["elapsed_sec"],
                record["animal_id"],
                event,
                json.dumps(fields, sort_keys=True),
            ]
        )
        self._event_csv_file.flush()

        trial = fields.get("trial", "")
        phase = fields.get("phase", "")
        detail = " ".join(f"{key}={value}" for key, value in fields.items())
        self._behavior_writer.writerow([f"{elapsed_sec:.6f}", event, trial, phase, detail])
        self._behavior_file.flush()
        if self.console_echo:
            detail = ", ".join(f"{key}={value}" for key, value in fields.items())
            if detail:
                print(f"[{elapsed_sec:8.3f}s] {event}: {detail}", flush=True)
            else:
                print(f"[{elapsed_sec:8.3f}s] {event}", flush=True)

    def log_lick_sample(self, raw_value: Any, active: bool) -> None:
        elapsed_sec = round(time.perf_counter() - self._start_time, 6)
        self._behavior_writer.writerow(
            [
                f"{elapsed_sec:.6f}",
                "lick_sample",
                "",
                "lick_monitor",
                f"raw_value={raw_value} active={int(bool(active))}",
            ]
        )
        self._behavior_file.flush()

    def close(self) -> None:
        if self._event_file and not self._event_file.closed:
            self._event_file.close()
        if self._event_csv_file and not self._event_csv_file.closed:
            self._event_csv_file.close()
        if self._behavior_file and not self._behavior_file.closed:
            self._behavior_file.close()
