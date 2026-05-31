# -*- coding: utf-8 -*-
"""
utils/frame_logger.py
=====================
Runs on PC1 (camera control computer).

Logs each expected widefield camera frame with its timestamp and LED channel.
Saves to: <func_dir_pc1>/<bids_stem>_frames.tsv

Column schema
-------------
frame           : frame index (0-based integer)
onset_sec       : seconds since Master-9 fired (same t=0 as events.tsv on PC2)
led_channel     : name of the LED illuminating this frame, e.g. "Green", "Blue"

LED cycle
---------
The LED cycle is specified as an ordered list that must match the timing
offsets pre-programmed in the Master-9 paradigm. It repeats indefinitely:

    3-channel GRB (default):  ["Green", "Red", "Blue"]
        Frame 0, 3, 6, ...  → Green  (CH6, 0 ms offset)
        Frame 1, 4, 7, ...  → Red    (CH5, 33 ms offset)
        Frame 2, 5, 8, ...  → Blue   (CH7, 66 ms offset)

    2-channel GB:             ["Green", "Blue"]
        Frame 0, 2, 4, ...  → Green  (CH6, 0 ms offset)
        Frame 1, 3, 5, ...  → Blue   (CH7, 45 ms offset)

    Single-channel G:         ["Green"]
        Every frame          → Green

Configure via the imaging.led_cycle list in your task YAML, then pass it
through camera_control.start_camera() → camera_listener → FrameLogger.
See puff_task.yaml for the config key.

Frame timing
------------
Timestamps are software-side estimates based on the expected Master-9
trigger interval (frame_rate Hz → 1/frame_rate seconds per frame).
For sub-millisecond precision, the Andor SDK can provide hardware
timestamps — this is a future improvement.
"""

import csv
import os
import time
import threading
import logging
from typing import List

logger_py = logging.getLogger(__name__)

# Default values — used when not specified in config
DEFAULT_LED_CYCLE   = ["Green", "Red", "Blue"]
DEFAULT_FRAME_RATE  = 33.333   # Hz — must match Master-9 CH3 paradigm

VALID_CHANNELS = {"Green", "Red", "Blue"}


class FrameLogger:

    def __init__(
        self,
        func_dir:   str,
        bids_stem:  str,
        led_cycle:  List[str] = None,
        frame_rate: float     = DEFAULT_FRAME_RATE,
    ):
        """
        Parameters
        ----------
        func_dir : str
            Full path to the func/ directory on PC1.
            e.g. "C:/Users/User/.../sub-m01/ses-1/func"
        bids_stem : str
            BIDS filename stem without suffix or extension.
            e.g. "sub-m01_ses-1_task-puff_run-1"
            The logger appends "_frames.tsv".
        led_cycle : list of str or None
            Ordered list of LED channel names matching the Master-9 paradigm.
            Each name must be "Green", "Red", or "Blue".
            The list repeats for the duration of the session.
            Examples:
                ["Green", "Red", "Blue"]  — 3-channel GRB (default)
                ["Green", "Blue"]         — 2-channel GB
                ["Green"]                 — single channel
            If None, defaults to ["Green", "Red", "Blue"].
        frame_rate : float
            Camera trigger rate in Hz. Must match Master-9 CH3 paradigm.
            Default 33.333 Hz (30 ms per frame).
        """
        # Validate and store LED cycle
        if led_cycle is None:
            led_cycle = DEFAULT_LED_CYCLE

        invalid = [ch for ch in led_cycle if ch not in VALID_CHANNELS]
        if invalid:
            raise ValueError(
                f"FrameLogger: invalid LED channel(s): {invalid}. "
                f"Must be one of {sorted(VALID_CHANNELS)}."
            )
        if len(led_cycle) == 0:
            raise ValueError("FrameLogger: led_cycle must contain at least one channel.")

        self._led_cycle       = led_cycle
        self._frame_interval  = 1.0 / frame_rate
        self._n_channels      = len(led_cycle)

        os.makedirs(func_dir, exist_ok=True)

        log_path         = os.path.join(func_dir, f"{bids_stem}_frames.tsv")
        self._log_file   = open(log_path, mode="w", newline="", encoding="utf-8")
        self._tsv_writer = csv.writer(self._log_file, delimiter="\t")
        self._tsv_writer.writerow(["frame", "onset_sec", "led_channel"])
        self._log_file.flush()

        self._running       = False
        self._thread        = None
        self._frame_count   = 0
        self._session_start = None

        logger_py.info(
            f"FrameLogger initialised — {log_path}\n"
            f"  LED cycle   : {' → '.join(led_cycle)} (repeating)\n"
            f"  Frame rate  : {frame_rate:.3f} Hz ({self._frame_interval*1000:.1f} ms/frame)"
        )

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self, session_start_time: float = None):
        """
        Start logging frames.

        Parameters
        ----------
        session_start_time : float or None
            Unix timestamp (time.time()) representing t=0 of the session.
            Pass the fire_time from _m9_start() for the most accurate sync.
            If None, uses time.time() at the moment start() is called.
        """
        if self._running:
            logger_py.warning("FrameLogger.start() called but already running")
            return

        self._running       = True
        self._frame_count   = 0
        self._session_start = session_start_time or time.time()

        self._thread = threading.Thread(
            target=self._log_loop,
            daemon=True,
            name="FrameLogger"
        )
        self._thread.start()
        logger_py.info("FrameLogger started")

    def stop(self):
        """Stop logging frames and flush the file."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._log_file and not self._log_file.closed:
            self._log_file.flush()
        logger_py.info(f"FrameLogger stopped — {self._frame_count} frames logged")

    def close(self):
        """Flush and close the TSV file."""
        self.stop()
        if self._log_file and not self._log_file.closed:
            self._log_file.flush()
            self._log_file.close()

    # ------------------------------------------------------------------
    # Logging loop
    # ------------------------------------------------------------------

    def _log_loop(self):
        """
        Background thread. Logs one row per expected trigger interval.
        onset_sec is relative to _session_start, matching events.tsv on PC2.
        """
        next_tick = time.perf_counter()

        while self._running:
            onset = time.time() - self._session_start
            led   = self._led_cycle[self._frame_count % self._n_channels]

            self._tsv_writer.writerow([
                self._frame_count,
                f"{onset:.4f}",
                led,
            ])

            # Flush every 30 frames (~1 s at 30 Hz) to reduce I/O overhead
            if self._frame_count % 30 == 0:
                self._log_file.flush()

            self._frame_count += 1

            # Sleep until next expected trigger
            next_tick += self._frame_interval
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # Running behind — skip ahead to stay in sync
                skipped   = int(-sleep_time / self._frame_interval) + 1
                next_tick += skipped * self._frame_interval
                logger_py.warning(
                    f"FrameLogger behind by {-sleep_time*1000:.1f} ms "
                    f"— skipping {skipped} frame(s)"
                )

    def __del__(self):
        self.close()
