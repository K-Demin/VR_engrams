# -*- coding: utf-8 -*-
"""
utils/trial_logger.py
=====================
Behaviour event logger for PC2.

Writes to: <func_dir_pc2>/<bids_stem>_events.tsv

Column schema
-------------
onset       : seconds since imaging_start_time (UTC Unix epoch, same t=0
              as frames.tsv on PC1 and Bonsai CsvWriter timestamps)
duration    : event duration in seconds
trial_type  : event name
trial       : trial number (blank for session-level events)
detail      : semicolon-separated key=value pairs

Clock alignment
---------------
All timestamps are UTC:
  - onset        : seconds since imaging_start_time (UTC Unix epoch from PC1)
  - t_on_utc     : UTC time-of-day string "HH:MM:SS.ffffff" (PC2 clock)
                   directly comparable to Bonsai CsvWriter (Kind=Utc) after
                   applying pc1_minus_pc2_seconds from clock_sync in config YAML

The config YAML snapshot saved alongside events.tsv contains a clock_sync
section with the per-session PC1-PC2 offset. Post-processing recipe:

    onset_from_bonsai = bonsai_seconds - clock_sync["pc1_minus_pc2_seconds"]
                        - clock_sync["imaging_start_unix"]
"""

import csv
import os
import time
import datetime
import yaml
from typing import Optional


class TrialLogger:

    def __init__(self, bids_path, config: dict):
        """
        Parameters
        ----------
        bids_path : BIDSPath
        config    : full experiment config dict (saved as YAML snapshot)
        """
        self.bids_path          = bids_path
        self.session_start_time: Optional[float] = None

        os.makedirs(bids_path.func_dir_pc2, exist_ok=True)

        self._setup_tsv()
        self._config = config   # held so update_clock_sync() can re-save

        # Save initial snapshot — will be re-saved after clock sync is added
        self._save_config(config)

        self.session_path = bids_path.func_dir_pc2

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_tsv(self):
        log_path = self.bids_path.events_tsv_pc2
        self._log_file   = open(log_path, mode="w", newline="", encoding="utf-8")
        self._tsv_writer = csv.writer(self._log_file, delimiter="\t")
        self._tsv_writer.writerow(["onset", "duration", "trial_type", "trial", "detail"])
        self._log_file.flush()
        print(f"Events log : {log_path}")

    def _save_config(self, config: dict):
        config_path = self.bids_path.config_yaml_pc2
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # ------------------------------------------------------------------
    # Clock sync metadata
    # ------------------------------------------------------------------

    def update_clock_sync(self, clock_sync: dict):
        """
        Store the PC1-PC2 clock offset metadata in the config YAML snapshot.

        Call this after measure_clock_offset() returns and after
        start_camera() fills in imaging_start_unix, so the YAML contains
        everything needed for post-processing alignment.

        Parameters
        ----------
        clock_sync : dict
            Returned by camera_control.measure_clock_offset(), with
            pc1_imaging_start_unix filled in by the pipeline script.
            Keys:
                pc1_minus_pc2_seconds       : float
                rtt_ms_median               : float
                rtt_ms_min                  : float
                n_samples                   : int
                pc1_imaging_start_unix      : float
                pc1_imaging_start_utc       : str  "HH:MM:SS.ffffff"
        """
        self._config["clock_sync"] = clock_sync
        self._save_config(self._config)
        print(
            f"Clock sync saved — "
            f"PC1 - PC2 = {clock_sync['pc1_minus_pc2_seconds']*1000:+.2f} ms  "
            f"RTT median = {clock_sync['rtt_ms_median']:.2f} ms"
        )

    # ------------------------------------------------------------------
    # Session start
    # ------------------------------------------------------------------

    def start_session(self, imaging_start_time: Optional[float] = None):
        """
        Anchor t=0 to imaging_start_time (UTC Unix epoch from PC1).

        Parameters
        ----------
        imaging_start_time : float or None
            time.time() on PC1 at the moment Master-9 fired.
            If None, falls back to time.time() on PC2 (bench testing).
        """
        if imaging_start_time is not None:
            self.session_start_time = imaging_start_time
            utc_str = datetime.datetime.utcfromtimestamp(imaging_start_time).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )
            print(f"Session clock: t=0 = {utc_str} UTC (Master-9 fire time, PC1)")
        else:
            self.session_start_time = time.time()
            print("Session clock: t=0 = local time.time() (no imaging_start_time provided)")

        self.log({"event": "session_start", "trial": -1})

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, data: dict):
        """
        Log a single event row to events.tsv.

        Required key  : "event" (str)
        Optional keys : "trial" (int), "duration" (float), any extras → detail
        Special key   : "t_on_utc" — if present in data, written as-is into detail.
                        Should be datetime.utcnow().strftime("%H:%M:%S.%f") on PC2,
                        directly comparable to Bonsai CsvWriter (Kind=Utc) after
                        applying clock_sync.pc1_minus_pc2_seconds.
        """
        if self.session_start_time is None:
            onset = 0.0
        else:
            onset = time.time() - self.session_start_time

        event    = data.get("event", "unknown")
        trial    = data.get("trial", "")
        duration = data.get("duration", 0)

        skip = {"event", "trial", "duration"}
        detail_pairs = [f"{k}={v}" for k, v in data.items() if k not in skip]
        detail = ";".join(detail_pairs)

        self._tsv_writer.writerow([
            f"{onset:.4f}",
            f"{duration:.4f}",
            event,
            trial,
            detail,
        ])
        self._log_file.flush()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        if self._log_file and not self._log_file.closed:
            self._log_file.flush()
            self._log_file.close()

    def __del__(self):
        self.close()
