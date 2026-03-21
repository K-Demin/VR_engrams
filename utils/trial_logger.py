# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:34:48 2026

@author: JoshB
"""

# utils/trial_logger.py
#
# Behaviour event logger for PC2.
# Saves to Y:/animal_id/date/puff_task_HH-MM-SS/behaviour_log.csv
#
# Matches the logging pattern from the somatosensory localiser task.

import csv
import hashlib
import os
import threading
import time
from datetime import datetime

import yaml


class TrialLogger:

    def __init__(self, animal_id: str, base_path: str, config: dict, session_path: str = None):
        """
        Parameters
        ----------
        animal_id    : Animal identifier, e.g. "M001"
        base_path    : Root data folder, e.g. "Y:/"
        config       : Full experiment config — saved as config_used.yaml
        session_path : If provided, use this exact folder path rather than
                       auto-generating one. Pass the same path used for
                       start_camera() so frame_log.csv and behaviour_log.csv
                       land in the same folder.
        """
        self.animal_id          = animal_id
        self.session_start_time = None
        self._session_start_perf = None
        self._lock = threading.Lock()

        if session_path is not None:
            self.session_path = session_path
            os.makedirs(self.session_path, exist_ok=True)
            print(f"Session folder: {self.session_path}")
        else:
            self._setup_session_folder(base_path, animal_id)

        self._setup_csv()
        self._save_config(config)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_session_folder(self, base_path: str, animal_id: str):
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H-%M-%S")

        self.session_path = os.path.join(
            base_path,
            animal_id,
            date_str,
            f"puff_task_{time_str}"
        )
        os.makedirs(self.session_path, exist_ok=True)
        print(f"Session folder: {self.session_path}")

    def _setup_csv(self):
        log_path = os.path.join(self.session_path, "behaviour_log.csv")
        self._log_file   = open(log_path, mode="w", newline="")
        self._csv_writer = csv.writer(self._log_file)

        # Header — matches localiser pattern, extended with extra fields
        self._csv_writer.writerow([
            "timestamp_sec",
            "event",
            "trial",
            "detail"        # any extra info (side, freq, outcome etc.)
        ])
        self._log_file.flush()

    def _save_config(self, config: dict):
        """Persist an immutable, hash-verifiable config snapshot for the session."""
        config_path = os.path.join(self.session_path, "config_used.yaml")
        config_text = yaml.safe_dump(config, sort_keys=True)

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_text)

        # Write a digest so downstream analyses can verify exact provenance.
        digest = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
        with open(os.path.join(self.session_path, "config_used.sha256"), "w", encoding="utf-8") as f:
            f.write(f"{digest}  config_used.yaml\n")

        # Best-effort lock: config snapshot should be read-only once written.
        try:
            os.chmod(config_path, 0o444)
            os.chmod(os.path.join(self.session_path, "config_used.sha256"), 0o444)
        except OSError:
            # Some network filesystems may not support chmod.
            pass

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def start_session(self):
        """Call this immediately before the task starts to set t=0."""
        self.session_start_time = time.time()
        self._session_start_perf = time.perf_counter()
        self.log({"event": "session_start", "trial": -1, "phase": "session"})

    def now_sec(self) -> float:
        """High-resolution elapsed time from session start."""
        if self._session_start_perf is None:
            return 0.0
        return time.perf_counter() - self._session_start_perf

    def log(self, data: dict):
        """
        Log a single event.

        Parameters
        ----------
        data : dict
            Must contain "event". Optional keys: "trial", any others
            are serialised into the "detail" column as key=value pairs.
        """
        timestamp = data.get("timestamp_sec")
        if timestamp is None:
            timestamp = self.now_sec()

        event  = data.get("event", "unknown")
        trial  = data.get("trial", "")

        # Everything except event and trial goes into detail column
        detail_keys = {k: v for k, v in data.items() if k not in ("event", "trial", "timestamp_sec")}
        detail = " ".join(f"{k}={v}" for k, v in detail_keys.items())

        if isinstance(timestamp, str):
            ts_value = timestamp
        else:
            ts_value = f"{float(timestamp):.6f}"

        with self._lock:
            self._csv_writer.writerow([
                ts_value,
                event,
                trial,
                detail
            ])
            self._log_file.flush()   # write immediately — safe against crashes

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        """Flush and close the log file."""
        if self._log_file and not self._log_file.closed:
            self._log_file.flush()
            self._log_file.close()

    def __del__(self):
        self.close()