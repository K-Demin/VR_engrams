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
import os
import time
import yaml
from datetime import datetime


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
        config_path = os.path.join(self.session_path, "config_used.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def start_session(self):
        """Call this immediately before the task starts to set t=0."""
        self.session_start_time = time.time()
        self.log({"event": "session_start", "trial": -1})

    def log(self, data: dict):
        """
        Log a single event.

        Parameters
        ----------
        data : dict
            Must contain "event". Optional keys: "trial", any others
            are serialised into the "detail" column as key=value pairs.
        """
        if self.session_start_time is None:
            timestamp = 0.0
        else:
            timestamp = time.time() - self.session_start_time

        event  = data.get("event", "unknown")
        trial  = data.get("trial", "")

        # Everything except event and trial goes into detail column
        detail_keys = {k: v for k, v in data.items() if k not in ("event", "trial")}
        detail = " ".join(f"{k}={v}" for k, v in detail_keys.items())

        self._csv_writer.writerow([
            f"{timestamp:.4f}",
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