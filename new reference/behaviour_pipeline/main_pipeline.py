# -*- coding: utf-8 -*-
"""
main_pipeline.py
================
Puff task entry point — PC2.

Usage
-----
    python main_pipeline.py configs/puff_task.yaml --animal m01 --session 1 --run 1

Arguments
---------
    config      : path to task YAML config
    --animal    : subject ID without "sub-" prefix, e.g. m01
    --session   : BIDS session number (integer, default 1).
                  Increment each new day the animal is in the setup.
                  Track the mapping to calendar dates in your spreadsheet.
    --run       : BIDS run number (integer, default 1).
                  Increment if you restart the task within the same session.

Output folder (BIDS)
--------------------
    <base_path_pc2>/sub-m01/ses-1/func/
        sub-m01_ses-1_task-puff_run-1_events.tsv     ← behaviour log
        sub-m01_ses-1_task-puff_run-1_config.yaml    ← config snapshot
        sub-m01_ses-1_task-puff_run-1_frames.tsv     ← frame log (written by PC1)
        sub-m01_ses-1_task-puff_run-1_body.avi       ← body camera (written by PC1)

    The same subfolder path is sent to PC1 so all files land in one place.
"""

import sys
import os
import yaml
import argparse
from datetime import datetime

from hardware.puff_controller import PuffController
from hardware.lick_detector import LickDetector
from hardware.audio_controller import AudioController
from utils.bids_path import BIDSPath
from utils.trial_logger import TrialLogger
from utils.camera_control import start_camera, stop_camera, ping_camera
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

# Create func/ folder on PC2 (PC1 creates its own copy when it receives the path)
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
# Hardware setup
# =======================================================
print("Initialising hardware...")
puff  = PuffController(config["hardware"]["puff_channel"])
lick  = LickDetector(config["hardware"]["lick_channel"])
audio = AudioController()

logger = TrialLogger(bids_path=bp, config=config)

# =======================================================
# Task setup
# =======================================================
task = PuffTaskFSM(config, puff, audio, lick, logger)

# =======================================================
# Run experiment
# =======================================================
try:
    print("\nStarting camera acquisition...")
    # Send the PC1 func directory so Bonsai and FrameLogger write there
    # Also send the BIDS stem so PC1 can name files correctly
    bids_stem = bp.filename("")   # "sub-m01_ses-1_task-puff_run-1_"
    ok, imaging_start_time = start_camera(
        session_path_pc1 = bp.func_dir_pc1,
        bids_stem        = bp.filename(""),   # stem without suffix; PC1 appends suffix+ext
    )
    if not ok:
        raise RuntimeError(
            "Failed to start camera acquisition. "
            "Check camera_listener.py log on PC1."
        )

    logger.start_session()
    print("Running behavioural task...")
    task.run()

finally:
    print("\nStopping camera acquisition...")
    stop_camera()
    logger.close()
    print("Experiment finished")
    print(f"\nData saved to: {bp.func_dir_pc2}")
