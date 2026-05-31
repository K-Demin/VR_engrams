# -*- coding: utf-8 -*-
"""
whisker_pipeline.py  --  PC2 entry point for whisker stimulation task

Usage:
    python whisker_pipeline.py configs/whisker_task.yaml --animal m01
"""

import sys
import os
import yaml
import argparse
from datetime import datetime

from hardware.puff_controller import PuffController
from utils.trial_logger import TrialLogger
from utils.camera_control import start_camera, stop_camera, ping_camera
from tasks.whisker_task_fsm import WhiskerTaskFSM

parser = argparse.ArgumentParser(description="Widefield Whisker Stimulation Task")
parser.add_argument("config",                 help="Path to config YAML")
parser.add_argument("--animal", required=True, help="Animal ID e.g. m01")
args = parser.parse_args()

with open(args.config) as f:
    config = yaml.safe_load(f)
config["animal_id"] = args.animal

BASE_PC2 = config.get("base_path_pc2", "Y:/")
BASE_PC1 = config.get("base_path_pc1", "C:/Users/User/Documents/Data/Josh_test/BehaviourData")

date_str  = datetime.now().strftime("%Y-%m-%d")
time_str  = datetime.now().strftime("%H-%M-%S")
subfolder = f"{args.animal}/{date_str}/whisker_{time_str}"

session_path_pc2 = f"{BASE_PC2.rstrip('/')}/{subfolder}"
session_path_pc1 = f"{BASE_PC1.rstrip('/')}/{subfolder}"

os.makedirs(session_path_pc2, exist_ok=True)
print(f"Session folder (PC2): {session_path_pc2}")
print(f"Session folder (PC1): {session_path_pc1}")

print("Checking camera connection...")
if not ping_camera():
    raise RuntimeError("Camera computer not responding.")
print("Camera connection OK")

print("Initialising hardware...")
puff = PuffController(config["hardware"]["puff_channel"])

logger = TrialLogger(
    animal_id    = args.animal,
    base_path    = BASE_PC2,
    config       = config,
    session_path = session_path_pc2
)

task = WhiskerTaskFSM(config, puff, logger)

try:
    print("Starting camera acquisition on PC1...")
    ok, imaging_start_time = start_camera(session_path_pc1)
    if not ok:
        raise RuntimeError("Failed to start camera acquisition.")

    # imaging_start_time is the moment START was sent over TCP.
    # This is used as t=0 for all session timing so PC2 stays in
    # sync with the Andor frame count rather than drifting behind.
    logger.start_session()
    print(f"Camera acquisition started.")
    print(f"Running whisker stimulation task...")
    task.run(imaging_start_time)

except KeyboardInterrupt:
    print("\nAborted by user (Ctrl+C)")
    logger.log({"event": "aborted_by_user"})

finally:
    print("Stopping camera acquisition...")
    stop_camera()
    logger.close()
    puff.close()
    print("Session finished")
