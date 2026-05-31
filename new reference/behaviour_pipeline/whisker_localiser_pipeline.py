# -*- coding: utf-8 -*-
"""
whisker_localiser_pipeline.py
==============================
Whisker localiser — block-design air puff task entry point — PC2.

Mirrors the structure of puff_pipeline.py and main_rest_task.py.
No audio, no lick detection — only air puff and imaging control.

Usage
-----
    python whisker_localiser_pipeline.py configs/whisker_localiser.yaml \\
           --animal m01 --session 1 --run 1

Arguments
---------
    config      : path to whisker_localiser.yaml
    --animal    : subject ID without "sub-" prefix, e.g. m01
    --session   : BIDS session number (integer, default 1)
    --run       : BIDS run number (integer, default 1)

Output folder (BIDS)
--------------------
    <base_path_pc2>/sub-m01/ses-1/func/
        sub-m01_ses-1_task-whisker_run-1_events.tsv    ← behaviour log
        sub-m01_ses-1_task-whisker_run-1_config.yaml   ← config + clock_sync
        sub-m01_ses-1_task-whisker_run-1_frames.tsv    ← frame timestamps (PC1)
        sub-m01_ses-1_task-whisker_run-1_body.avi      ← body camera (PC1)

Session structure logged to events.tsv
---------------------------------------
    onset   trial_type      trial   detail
    0.000   session_start   -1
    0.031   baseline_start          duration=30.0
    30.03   baseline_end
    30.03   rest_start      0       duration=28.4          ← inter-block rest
    58.43   rest_end        0
    58.43   block_start     0       duration=20.0;puff_interval_s=2.0;...
    58.46   puff            0       puff_n=1;duration=0.05
    60.46   puff            0       puff_n=2;duration=0.05
    ...
    78.43   block_end       0       puffs_delivered=10
    78.43   rest_start      1       ...
    ...

Clock alignment
---------------
imaging_start_time (UTC Unix epoch, PC1 Master-9 fire) is passed into both
logger.start_session() and task.run() so events.tsv onset and frames.tsv
onset_sec share the same t=0. The PC1–PC2 clock offset is measured before
acquisition and stored in the config YAML under clock_sync.
"""

import datetime as _dt
import yaml
import argparse

from hardware.ir_led_controller import IRLEDController
from hardware.puff_controller import PuffController
from utils.bids_path import BIDSPath
from utils.trial_logger import TrialLogger
from utils.camera_control import (
    start_camera, stop_camera, ping_camera, measure_clock_offset
)
from tasks.whisker_localiser_fsm import WhiskerLocaliserFSM

# =======================================================
# CLI
# =======================================================
parser = argparse.ArgumentParser(description="Whisker Localiser — block-design puff task")
parser.add_argument("config",                   help="Path to whisker_localiser.yaml")
parser.add_argument("--animal",  required=True, help="Animal ID, e.g. m01")
parser.add_argument("--session", type=int, default=1,
                    help="BIDS session number (default 1). Increment per day.")
parser.add_argument("--run",     type=int, default=1,
                    help="BIDS run number (default 1). Increment if restarting same session.")
args = parser.parse_args()

# =======================================================
# Load config
# =======================================================
with open(args.config) as f:
    config = yaml.safe_load(f)

config["animal_id"]   = args.animal
config["session_num"] = args.session
config["run_num"]     = args.run

led_cycle  = config.get("imaging", {}).get("led_cycle",  ["Green", "Red", "Blue"])
frame_rate = config.get("imaging", {}).get("frame_rate", 33.333)

# =======================================================
# Build BIDS session paths
# =======================================================
bp = BIDSPath(
    project_root_pc2 = config.get("base_path_pc2", "Y:/"),
    project_root_pc1 = config.get("base_path_pc1", "C:/Users/User/Documents/Data"),
    sub              = args.animal,
    ses              = args.session,
    task             = config.get("task_label", "whisker"),
    run              = args.run,
)

bp.makedirs()
print(bp.summary())

# =======================================================
# Validate timing before touching any hardware
# =======================================================
t        = config["timing"]
n_blocks = config["session"]["n_blocks"]

if t["puff_interval_s"] <= t["puff_duration_s"]:
    raise ValueError(
        f"puff_interval_s ({t['puff_interval_s']}s) must be greater than "
        f"puff_duration_s ({t['puff_duration_s']}s)"
    )

if t["block_duration_s"] < t["puff_interval_s"]:
    raise ValueError(
        f"block_duration_s ({t['block_duration_s']}s) must be at least "
        f"puff_interval_s ({t['puff_interval_s']}s) to deliver at least one puff"
    )

# Minimum session length uses the smallest possible rest at every slot:
#   baseline + n_blocks × (min_rest + block_duration) + min_rest (tail)
# For fixed mode min_rest = rest_duration_s; for random it is rest_min_s.
min_rest_s = (
    t.get("rest_duration_s", 30.0)
    if t.get("rest_mode", "random") == "fixed"
    else t.get("rest_min_s", 20.0)
)
min_session_s = (
    t.get("baseline_s", 30.0)
    + n_blocks * (min_rest_s + t["block_duration_s"])
    + min_rest_s   # minimum tail rest
)
if t["total_duration_s"] < min_session_s:
    raise ValueError(
        f"total_duration_s ({t['total_duration_s']}s) is too short.\n"
        f"  Minimum needed: {min_session_s:.1f}s\n"
        f"  ({t.get('baseline_s', 30.0):.0f}s baseline  +  "
        f"{n_blocks} blocks × ({min_rest_s:.0f}s min_rest + "
        f"{t['block_duration_s']:.0f}s block)  +  "
        f"{min_rest_s:.0f}s tail rest)\n"
        f"  Increase total_duration_s or reduce n_blocks / block_duration_s."
    )

# =======================================================
# Check camera system is reachable
# =======================================================
print("\nChecking camera connection...")
if not ping_camera():
    raise RuntimeError(
        "Camera computer not responding. "
        "Make sure camera_listener.py is running on PC1."
    )
print("Camera connection OK")

# =======================================================
# Hardware setup — IR LED (optional)
# =======================================================
ir_led_channel = config.get("hardware", {}).get("ir_led_channel")
ir_led = None

if ir_led_channel:
    print(f"Initialising IR LED on {ir_led_channel}...")
    ir_led = IRLEDController(ir_led_channel)
    print("IR LED ready")
else:
    print("No ir_led_channel in config — IR LED sync disabled")

# =======================================================
# Hardware setup — puff only (no lick, no audio)
# =======================================================
print("Initialising puff hardware...")
puff = PuffController(config["hardware"]["puff_channel"])
print("Puff hardware ready")

# =======================================================
# Logger + task
# logger.start_session() is called inside task.run() once
# imaging_start_time is confirmed from PC1.
# =======================================================
logger = TrialLogger(bids_path=bp, config=config)

task = WhiskerLocaliserFSM(config, logger, ir_led=ir_led)

# =======================================================
# Run experiment
# =======================================================
try:
    # Measure PC1-PC2 clock offset before acquisition starts.
    # Stored in config YAML for Bonsai timestamp alignment in post-processing.
    print("\nMeasuring PC1-PC2 clock offset...")
    clock_sync = measure_clock_offset()

    print(f"\nStarting camera acquisition (LED cycle: {' → '.join(led_cycle)})...")
    ok, imaging_start_time = start_camera(
        session_path_pc1 = bp.func_dir_pc1,
        bids_stem        = bp.filename(""),
        led_cycle        = led_cycle,
    )
    if not ok:
        raise RuntimeError(
            "Failed to start camera acquisition. "
            "Check camera_listener.py log on PC1."
        )

    # Store imaging start in clock_sync and persist to config YAML
    clock_sync["pc1_imaging_start_unix"] = imaging_start_time
    clock_sync["pc1_imaging_start_utc"]  = _dt.datetime.utcfromtimestamp(
        imaging_start_time).strftime("%H:%M:%S.%f")
    logger.update_clock_sync(clock_sync)

    print("Running whisker localiser...")
    task.run(imaging_start_time)

finally:
    print("\nStopping camera acquisition...")
    stop_camera()
    if ir_led is not None:
        ir_led.close()
    logger.close()
    print("Experiment finished")
    print(f"\nData saved to: {bp.func_dir_pc2}")
