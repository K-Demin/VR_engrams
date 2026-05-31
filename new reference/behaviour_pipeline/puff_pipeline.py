# -*- coding: utf-8 -*-
"""
puff_pipeline.py
================
Air-puff conditioning task entry point — PC2.

Usage
-----
    python puff_pipeline.py configs/puff_task.yaml --animal m01 --session 1 --run 1

Arguments
---------
    config      : path to task YAML config
    --animal    : subject ID without "sub-" prefix, e.g. m01
    --session   : BIDS session number (integer, default 1)
    --run       : BIDS run number (integer, default 1)

Output folder (BIDS)
--------------------
    <base_path_pc2>/sub-m01/ses-1/func/
        sub-m01_ses-1_task-puff_run-1_events.tsv    <- behaviour log (PC2)
        sub-m01_ses-1_task-puff_run-1_config.yaml   <- config snapshot (PC2)
        sub-m01_ses-1_task-puff_run-1_frames.tsv    <- frame timestamps (PC1)
        sub-m01_ses-1_task-puff_run-1_body.avi      <- body camera (PC1 via Bonsai)

Clock alignment
---------------
imaging_start_time (Unix timestamp from PC1, moment Master-9 fired) is
passed into logger.start_session() and task.run() so that events.tsv onset
and frames.tsv onset_sec share the same t=0.

IR LED sync
-----------
Three pulses fired via hardware.ir_led_channel:
    ir_sync_task_start    — before baseline, blocking
    ir_sync_imaging_start — just before FSM loop, non-blocking
    ir_sync_task_end      — after all trials complete, blocking
Omit ir_led_channel from config to silently disable.
"""

import yaml
import argparse

from hardware.ir_led_controller import IRLEDController
from hardware.puff_controller import PuffController
from hardware.lick_detector import LickDetector
from hardware.audio_controller import AudioController
from utils.bids_path import BIDSPath
from utils.trial_logger import TrialLogger
from utils.camera_control import start_camera, stop_camera, ping_camera, measure_clock_offset
from tasks.puff_task_fsm import PuffTaskFSM

# =======================================================
# CLI
# =======================================================
parser = argparse.ArgumentParser(description="Widefield Puff Task")
parser.add_argument("config",                   help="Path to config YAML")
parser.add_argument("--animal",  required=True, help="Animal ID, e.g. m01")
parser.add_argument("--session", type=int, default=1,
                    help="BIDS session number (default 1). Increment per day in setup.")
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

# Read LED cycle from config — passed to FrameLogger on PC1 via camera_control
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
    task             = config.get("task_label", "puff"),
    run              = args.run,
)

bp.makedirs()
print(bp.summary())

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
# Hardware setup — behaviour peripherals
# =======================================================
print("Initialising behaviour hardware...")
puff  = PuffController(config["hardware"]["puff_channel"])
lick  = LickDetector(config["hardware"]["lick_channel"])
audio = AudioController()
print("Hardware ready")

# =======================================================
# Logger + task
# Note: logger.start_session() is called inside task.run()
# after imaging_start_time is confirmed from PC1.
# =======================================================
logger = TrialLogger(bids_path=bp, config=config)

task = PuffTaskFSM(config, puff, audio, lick, logger, ir_led=ir_led)

# =======================================================
# Run experiment
# =======================================================
try:
    # Measure PC1-PC2 clock offset before starting acquisition.
    # Stored in config YAML for post-processing alignment with Bonsai timestamps.
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

    # Store imaging start time in clock_sync and save to config YAML
    import datetime as _dt
    clock_sync["pc1_imaging_start_unix"] = imaging_start_time
    clock_sync["pc1_imaging_start_utc"]  = _dt.datetime.utcfromtimestamp(
        imaging_start_time).strftime("%H:%M:%S.%f")
    logger.update_clock_sync(clock_sync)

    print("Running puff task...")
    task.run(imaging_start_time)

finally:
    print("\nStopping camera acquisition...")
    stop_camera()
    if ir_led is not None:
        ir_led.close()
    logger.close()
    print("Experiment finished")
    print(f"\nData saved to: {bp.func_dir_pc2}")
