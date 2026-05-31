from __future__ import annotations

import json
import time
import csv
from copy import deepcopy
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
    bids_path: Any | None = None
    _start_time: float = field(default_factory=time.perf_counter, init=False)
    _session_started: bool = field(default=False, init=False)
    session_start_unix: float | None = field(default=None, init=False)
    pc1_minus_pc2_seconds: float = field(default=0.0, init=False)
    _event_file: Any = field(default=None, init=False)
    _event_csv_file: Any = field(default=None, init=False)
    _event_csv_writer: Any = field(default=None, init=False)
    _events_tsv_file: Any = field(default=None, init=False)
    _events_tsv_writer: Any = field(default=None, init=False)
    _behavior_file: Any = field(default=None, init=False)
    _behavior_writer: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.config = deepcopy(self.config)
        if self.bids_path is not None:
            self.bids_path.makedirs()
            self.session_dir = Path(self.bids_path.func_dir_pc2)
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.session_dir = self.root_dir / self.animal_id / f"{self.run_name}_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._event_path = self.session_dir / "events.jsonl"
        self._event_file = self._event_path.open("w", encoding="utf-8")

        self._event_csv_path = self.session_dir / "events.csv"
        self._event_csv_file = self._event_csv_path.open("w", encoding="utf-8", newline="")
        self._event_csv_writer = csv.writer(self._event_csv_file)
        self._event_csv_writer.writerow(["timestamp_utc", "elapsed_sec", "animal_id", "event", "fields_json"])

        if self.bids_path is not None:
            self._events_tsv_path = self.bids_path.events_tsv_pc2
            self._events_tsv_file = self._events_tsv_path.open("w", encoding="utf-8", newline="")
            self._events_tsv_writer = csv.writer(self._events_tsv_file, delimiter="\t", lineterminator="\n")
            self._events_tsv_writer.writerow(["onset", "duration", "trial_type", "trial", "detail"])

        self._behavior_path = self.session_dir / "behavior_log.csv"
        self._behavior_file = self._behavior_path.open("w", encoding="utf-8", newline="")
        self._behavior_writer = csv.writer(self._behavior_file)
        self._behavior_writer.writerow(["timestamp_sec", "event", "trial", "phase", "detail"])

        self.snapshot_parameters()

    def snapshot_parameters(self) -> None:
        snapshot_path = self.session_dir / "parameters_snapshot.yaml"
        with snapshot_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config, handle, sort_keys=False)
        if self.bids_path is not None:
            with self.bids_path.config_yaml_pc2.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(self.config, handle, sort_keys=False)

    def update_clock_sync(self, clock_sync: dict[str, Any]) -> None:
        self.config["clock_sync"] = clock_sync
        self.pc1_minus_pc2_seconds = float(clock_sync.get("pc1_minus_pc2_seconds", 0.0) or 0.0)
        if self.bids_path is not None:
            with self.bids_path.clock_sync_yaml_pc2.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(clock_sync, handle, sort_keys=False)
        self.snapshot_parameters()

    def start_session(self, session_start_unix: float | None = None) -> None:
        self._start_time = time.perf_counter()
        self.session_start_unix = session_start_unix
        self._session_started = True
        self.config.setdefault("clock_sync", {})
        self.config["clock_sync"]["session_t0_source"] = "pc1_imaging_start_unix" if session_start_unix else "pc2_perf_counter"
        self.config["clock_sync"]["session_start_unix"] = session_start_unix
        self.snapshot_parameters()
        self.log_event("session_start", session_start_unix=session_start_unix)

    @property
    def session_started(self) -> bool:
        return self._session_started

    def elapsed_sec(self) -> float:
        if self.session_start_unix is not None:
            estimated_pc1_now = time.time() + self.pc1_minus_pc2_seconds
            return estimated_pc1_now - float(self.session_start_unix)
        return time.perf_counter() - self._start_time

    def log_event(self, event: str, **fields: Any) -> None:
        elapsed_sec = round(self.elapsed_sec(), 6)
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
        self._write_events_tsv(event=event, fields=fields, elapsed_sec=elapsed_sec)

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

    def _write_events_tsv(self, event: str, fields: dict[str, Any], elapsed_sec: float) -> None:
        if self._events_tsv_writer is None:
            return

        duration = fields.get("duration", fields.get("duration_sec", 0.0))
        trial = fields.get("trial", fields.get("trial_index", "n/a"))
        detail_fields = {
            key: value
            for key, value in fields.items()
            if key not in {"duration", "duration_sec", "trial", "trial_index"}
        }
        detail = json.dumps(detail_fields, sort_keys=True, default=str) if detail_fields else "n/a"
        self._events_tsv_writer.writerow([f"{elapsed_sec:.6f}", duration, event, trial, detail])
        self._events_tsv_file.flush()

    def log_lick_sample(self, raw_value: Any, active: bool) -> None:
        elapsed_sec = round(self.elapsed_sec(), 6)
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
        if self._events_tsv_file and not self._events_tsv_file.closed:
            self._events_tsv_file.close()
        if self._behavior_file and not self._behavior_file.closed:
            self._behavior_file.close()
