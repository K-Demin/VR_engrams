# -*- coding: utf-8 -*-
"""
utils/camera_control.py  —  PC2
================================
Sends TCP commands to camera_listener.py on PC1.

Protocol
--------
All commands are newline-terminated ASCII strings.

    PING
        → "PONG"

    TIMESYNC
        → "TIMESYNC <pc1_unix> <pc1_timeofday>"
          pc1_unix       : PC1 time.time() at the moment of response, 6 d.p.
          pc1_timeofday  : PC1 local time-of-day string "HH:MM:SS.fffffff"
                           same format as Bonsai CsvWriter timestamps
        Used to measure the PC1–PC2 wall-clock offset before each session.
        Call measure_clock_offset() rather than this command directly.

    START <func_dir_pc1>|<bids_stem>|<led_cycle>
        → "OK <unix_timestamp>"   (imaging_start_time from PC1)
        → "ERROR"                 on failure

    STOP
        → "OK"

    EXIT
        → "OK"

Clock offset measurement
------------------------
measure_clock_offset() sends TIMESYNC five times, computes the median
PC1–PC2 offset using the NTP half-RTT method, and returns a metadata dict:

    {
        "pc1_minus_pc2_seconds" : float   # positive = PC1 ahead of PC2
        "rtt_ms_median"         : float   # median round-trip time in ms
        "n_samples"             : int     # number of successful exchanges
        "pc1_imaging_start_timeofday" : str  # filled in by start_camera()
        "pc1_imaging_start_unix"      : float
    }

Post-processing alignment
--------------------------
To convert a Bonsai CsvWriter timestamp (PC1 time-of-day string) to
seconds-since-imaging-start on the same clock as events.tsv:

    from datetime import datetime, date

    def bonsai_to_onset(bonsai_tod_str, sync_meta, date_str="2026-05-21"):
        # 1. Parse Bonsai time-of-day (7-digit fractional seconds)
        bonsai_dt = datetime.strptime(
            date_str + " " + bonsai_tod_str[:15],   # trim to microseconds
            "%Y-%m-%d %H:%M:%S.%f"
        )
        bonsai_unix = bonsai_dt.timestamp()

        # 2. Shift from PC1 clock to PC2 clock
        bonsai_unix_pc2 = bonsai_unix - sync_meta["pc1_minus_pc2_seconds"]

        # 3. Express relative to imaging start (same as events.tsv onset)
        onset = bonsai_unix_pc2 - sync_meta["pc1_imaging_start_unix"]
        return onset
"""

import socket
import time
import datetime
import statistics
import logging
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

PC1_HOST     = "115.145.185.228"
PC1_PORT     = 5000
TIMEOUT_PING = 5.0
TIMEOUT_CMD  = 20.0

DEFAULT_LED_CYCLE = ["Green", "Blue"]   # CH5 (Red) is OFF in current paradigm
N_TIMESYNC_SAMPLES = 5    # number of TIMESYNC exchanges to average


def _send_command(command: str, timeout: float = TIMEOUT_CMD):
    """
    Send a single command to PC1 and return (response_str, t_send, t_receive).
    t_send    : time.time() immediately before bytes leave PC2
    t_receive : time.time() immediately after response bytes arrive on PC2
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((PC1_HOST, PC1_PORT))
            t_send = time.time()
            s.sendall(f"{command}\n".encode("utf-8"))
            response = s.recv(1024).decode("utf-8").strip()
            t_receive = time.time()
            logger.debug(f"CMD={command!r}  RESP={response!r}")
            return response, t_send, t_receive
    except socket.timeout:
        raise ConnectionError(f"Timeout ({timeout}s) waiting for response to {command!r}")
    except OSError as e:
        raise ConnectionError(f"Socket error sending {command!r}: {e}")


def ping_camera() -> bool:
    """Return True if PC1 camera listener is reachable."""
    try:
        resp, _, _ = _send_command("PING", timeout=TIMEOUT_PING)
        ok = resp == "PONG"
        if ok:
            logger.info("PC1 camera listener: online (PONG received)")
        else:
            logger.warning(f"Unexpected PING response: {resp!r}")
        return ok
    except ConnectionError as e:
        logger.error(f"ping_camera() failed: {e}")
        return False


def measure_clock_offset(n_samples: int = N_TIMESYNC_SAMPLES) -> Dict:
    """
    Measure the PC1–PC2 wall-clock offset using repeated TIMESYNC exchanges.

    Uses the NTP half-RTT method:
        estimated_offset = pc1_unix - (t_send + rtt/2)

    where rtt = t_receive - t_send (full round-trip time on PC2's clock).

    Runs n_samples exchanges and takes the median offset (more robust than
    the mean against occasional network spikes).

    Returns
    -------
    dict with keys:
        pc1_minus_pc2_seconds   : float  — median clock offset in seconds.
                                           Positive = PC1 clock is ahead of PC2.
        rtt_ms_median           : float  — median round-trip time in ms
        rtt_ms_min              : float  — minimum round-trip time in ms
        n_samples               : int    — number of successful exchanges
        pc1_imaging_start_timeofday : str   — filled in later by start_camera()
        pc1_imaging_start_unix      : float — filled in later by start_camera()

    Raises
    ------
    RuntimeError if fewer than 2 exchanges succeed.
    """
    offsets = []
    rtts    = []

    for i in range(n_samples):
        try:
            resp, t_send, t_receive = _send_command("TIMESYNC", timeout=TIMEOUT_PING)
            # Response format: "TIMESYNC <pc1_unix> <pc1_timeofday>"
            parts = resp.split()
            if len(parts) != 3 or parts[0] != "TIMESYNC":
                logger.warning(f"Unexpected TIMESYNC response: {resp!r}")
                continue

            pc1_unix = float(parts[1])
            rtt      = t_receive - t_send
            # NTP half-RTT estimate: assume symmetric network delay
            offset   = pc1_unix - (t_send + rtt / 2.0)

            offsets.append(offset)
            rtts.append(rtt * 1000.0)   # convert to ms

            logger.debug(
                f"TIMESYNC {i+1}/{n_samples}: "
                f"offset={offset*1000:.2f}ms  rtt={rtt*1000:.2f}ms"
            )
            time.sleep(0.05)   # small gap between samples

        except (ConnectionError, ValueError) as e:
            logger.warning(f"TIMESYNC sample {i+1} failed: {e}")

    if len(offsets) < 2:
        raise RuntimeError(
            f"Clock sync failed — only {len(offsets)}/{n_samples} "
            f"TIMESYNC exchanges succeeded."
        )

    median_offset = statistics.median(offsets)
    median_rtt    = statistics.median(rtts)
    min_rtt       = min(rtts)

    logger.info(
        f"Clock sync complete ({len(offsets)} samples): "
        f"PC1 - PC2 = {median_offset*1000:+.2f} ms  "
        f"RTT median={median_rtt:.2f}ms  min={min_rtt:.2f}ms"
    )

    return {
        "pc1_minus_pc2_seconds":          round(median_offset, 6),
        "rtt_ms_median":                  round(median_rtt, 3),
        "rtt_ms_min":                     round(min_rtt, 3),
        "n_samples":                      len(offsets),
        # These two fields are filled in by start_camera() once Master-9 fires
        "pc1_imaging_start_timeofday":    None,
        "pc1_imaging_start_unix":         None,
    }


def start_camera(
    session_path_pc1: str,
    bids_stem:        str = "",
    led_cycle:        Optional[List[str]] = None,
) -> tuple:
    """
    Tell PC1 to start Master-9 + FrameLogger acquisition.

    Parameters
    ----------
    session_path_pc1 : str
        Full path to the func/ directory on PC1.
    bids_stem : str
        BIDS filename stem with trailing underscore.
        e.g. "sub-m01_ses-1_task-puff_run-1_"
    led_cycle : list of str or None
        Ordered list of LED channel names matching the Master-9 paradigm.
        Each entry must be "Green", "Red", or "Blue".
        If None, defaults to ["Green", "Red", "Blue"].

    Returns
    -------
    (True, imaging_start_time)   on success
    (False, None)                on failure
    """
    if led_cycle is None:
        led_cycle = DEFAULT_LED_CYCLE

    led_cycle_str = ",".join(led_cycle)

    try:
        payload = f"{session_path_pc1}|{bids_stem}|{led_cycle_str}"
        resp, _, _ = _send_command(f"START {payload}", timeout=TIMEOUT_CMD)

        if resp.startswith("OK"):
            parts = resp.split()
            if len(parts) >= 2:
                imaging_start_time = float(parts[1])
                logger.info(
                    f"Camera acquisition started — imaging t=0: {imaging_start_time:.6f}  "
                    f"LED cycle: {' → '.join(led_cycle)}"
                )
                return True, imaging_start_time
            else:
                logger.warning("PC1 sent OK without timestamp — using local time")
                return True, time.time()
        else:
            logger.error(f"START failed, PC1 response: {resp!r}")
            return False, None

    except ConnectionError as e:
        logger.error(f"start_camera() failed: {e}")
        return False, None


def stop_camera() -> bool:
    try:
        resp, _, _ = _send_command("STOP", timeout=TIMEOUT_CMD)
        ok = resp == "OK"
        if ok:
            logger.info("Camera acquisition stopped")
        else:
            logger.error(f"STOP failed, PC1 response: {resp!r}")
        return ok
    except ConnectionError as e:
        logger.error(f"stop_camera() failed: {e}")
        return False


def exit_listener() -> bool:
    try:
        resp, _, _ = _send_command("EXIT", timeout=TIMEOUT_CMD)
        ok = resp == "OK"
        if ok:
            logger.info("PC1 camera listener shut down")
        return ok
    except ConnectionError as e:
        logger.error(f"exit_listener() failed: {e}")
        return False
