# -*- coding: utf-8 -*-
"""
Created on Wed Mar 11 14:36:09 2026

@author: NeuRLab
"""

# utils/frame_logger.py
#
# Runs on PC1 (camera control computer).
# Logs each camera frame with its timestamp and LED channel (G/R/B).
# Saves to the shared session folder on Y:/
#
# The GRB cycle repeats every 3 frames:
#   Frame 0, 3, 6, ... → Green  (CH6, offset 0ms)
#   Frame 1, 4, 7, ... → Red    (CH5, offset 30ms)
#   Frame 2, 5, 8, ... → Blue   (CH7, offset 60ms)
#
# Frame timestamps are recorded at the moment the camera trigger fires
# (i.e. when Master-9 CH3 pulses). Since we control the trigger in
# software via Master-9, we log the timestamp immediately after
# start_sequence() is called and then at each expected trigger interval.
#
# Usage:
#   logger = FrameLogger(session_path="Y:/M001/2026-03-11/puff_task_14-00-00")
#   logger.start()          # call when acquisition starts
#   logger.stop()           # call when acquisition stops
#   logger.close()          # call at end of session

import csv
import os
import time
import threading
import logging

logger_py = logging.getLogger(__name__)

# GRB cycle — must match Master-9 paradigm
FRAME_INTERVAL_S = 1.0 / 33.333   # ~30ms — matches CH3 interval
LED_CYCLE        = ["Green", "Red", "Blue"]   # frame 0, 1, 2 then repeats


class FrameLogger:

    def __init__(self, session_path: str):
        """
        Parameters
        ----------
        session_path : str
            Full path to the session folder, e.g.
            "Y:/M001/2026-03-11/puff_task_14-00-00"
            Must already exist (created by TrialLogger on PC2,
            or passed in from camera_listener).
        """
        self.session_path = session_path
        os.makedirs(session_path, exist_ok=True)

        log_path         = os.path.join(session_path, "frame_log.csv")
        self._log_file   = open(log_path, mode="w", newline="")
        self._csv_writer = csv.writer(self._log_file)
        self._csv_writer.writerow(["frame", "timestamp_sec", "led_channel"])
        self._log_file.flush()

        self._running         = False
        self._thread          = None
        self._frame_count     = 0
        self._session_start   = None

        logger_py.info(f"FrameLogger initialised — {log_path}")

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self):
        """
        Start logging frames.
        Call this immediately after Master-9 start_sequence() succeeds.
        """
        if self._running:
            logger_py.warning("FrameLogger.start() called but already running")
            return

        self._running       = True
        self._frame_count   = 0
        self._session_start = time.time()

        self._thread = threading.Thread(
            target=self._log_loop,
            daemon=True,
            name="FrameLogger"
        )
        self._thread.start()
        logger_py.info("FrameLogger started")

    def stop(self):
        """
        Stop logging frames.
        Call this immediately after Master-9 stop() is called.
        """
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger_py.info(f"FrameLogger stopped — {self._frame_count} frames logged")

    def close(self):
        """Flush and close the CSV file."""
        self.stop()
        if self._log_file and not self._log_file.closed:
            self._log_file.flush()
            self._log_file.close()

    # ------------------------------------------------------------------
    # Logging loop
    # ------------------------------------------------------------------

    def _log_loop(self):
        """
        Runs in a background thread.
        Logs one row per frame at the expected trigger interval.

        Note: This is a software-side timestamp — it records when we
        expect the frame to have been triggered based on the Master-9
        paradigm interval. For sub-millisecond precision, you would
        read back a hardware timestamp from the camera SDK instead.
        """
        next_tick = time.perf_counter()

        while self._running:
            now       = time.perf_counter()
            timestamp = now - (self._session_start - time.perf_counter() + time.perf_counter())

            # Simpler: timestamp relative to session start
            timestamp = time.time() - self._session_start

            led = LED_CYCLE[self._frame_count % 3]

            self._csv_writer.writerow([
                self._frame_count,
                f"{timestamp:.4f}",
                led
            ])

            # Flush every 30 frames (~1 second) to reduce I/O overhead
            if self._frame_count % 30 == 0:
                self._log_file.flush()

            self._frame_count += 1

            # Sleep until next expected trigger
            next_tick += FRAME_INTERVAL_S
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # We're running behind — skip ahead to stay in sync
                skipped = int(-sleep_time / FRAME_INTERVAL_S) + 1
                next_tick += skipped * FRAME_INTERVAL_S
                logger_py.warning(f"FrameLogger behind by {-sleep_time*1000:.1f}ms — skipping {skipped} frames")

    def __del__(self):
        self.close()