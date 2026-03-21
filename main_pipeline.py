# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:39:56 2026

@author: JoshB
"""
# python main_pipeline.py configs/puff_task.yaml --animal m01

import sys
import os
import yaml
import argparse
from datetime import datetime

from hardware.puff_controller import PuffController
from hardware.lick_detector import LickDetector
from hardware.audio_controller import AudioController
from utils.trial_logger import TrialLogger
from utils.camera_control import start_camera, stop_camera, ping_camera
from tasks.puff_task_fsm import PuffTaskFSM

# =======================================================
# CLI
# =======================================================
parser = argparse.ArgumentParser(description="Widefield Puff Task")
parser.add_argument("config",                 help="Path to config YAML")
parser.add_argument("--animal", required=True, help="Animal ID e.g. m01")
args = parser.parse_args()

# =======================================================
# Load config
# =======================================================
with open(args.config) as f:
    config = yaml.safe_load(f)

config["animal_id"] = args.animal

# =======================================================
# Session folder
# PC2 writes to Y:/ (mapped shared drive)
# PC1 writes to its local path — sent in the START command
# Both use the same subfolder structure so files are co-located
# =======================================================
BASE_PC2 = config.get("base_path_pc2", "Y:/")
BASE_PC1 = config.get("base_path_pc1", "C:/Users/User/Documents/Data/Josh_test/BehaviourData")

date_str     = datetime.now().strftime("%Y-%m-%d")
time_str     = datetime.now().strftime("%H-%M-%S")
subfolder    = f"{args.animal}/{date_str}/puff_task_{time_str}"

session_path_pc2 = f"{BASE_PC2.rstrip('/')}/{subfolder}"
session_path_pc1 = f"{BASE_PC1.rstrip('/')}/{subfolder}"

os.makedirs(session_path_pc2, exist_ok=True)
print(f"Session folder (PC2): {session_path_pc2}")
print(f"Session folder (PC1): {session_path_pc1}")

# =======================================================
# Check camera system is reachable
# =======================================================
print("Checking camera connection...")
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
audio = AudioController()

logger = TrialLogger(
    animal_id    = args.animal,
    base_path    = BASE_PC2,
    config       = config,
    session_path = session_path_pc2
)

# =======================================================
# Task setup
# =======================================================
task = PuffTaskFSM(config, puff, audio, None, logger)


lick = LickDetector(
    sensor_channel=config["hardware"]["lick_channel"],
    logger=logger,
    threshold=config["hardware"].get("lick_threshold", 0.5),
    logic_mode=config["hardware"].get("lick_logic_mode", "high_is_lick"),
    refractory_sec=config["hardware"].get("lick_refractory_sec", 0.05),
    sample_interval_sec=config["hardware"].get("lick_sample_interval_sec", 0.001),
    valve_channel=config["hardware"].get("valve_channel"),
    valve_open_duration_sec=config["hardware"].get("valve_open_duration", 0.04),
    reward_on_lick=config["hardware"].get("reward_on_lick", False),
    trial_provider=lambda: task.trial,
    phase_provider=lambda: task.state,
)

task.lick = lick

# =======================================================
# Run experiment
# =======================================================
try:
    print("Starting camera acquisition...")
    if not start_camera(session_path_pc1):
        raise RuntimeError(
            "Failed to start camera acquisition. "
            "Check camera_listener.py log on PC1."
        )

    logger.start_session()
    lick.start()
    print("Running behavioural task...")
    task.run()

finally:
    print("Stopping camera acquisition...")
    stop_camera()
    lick.stop()
    logger.close()
    print("Experiment finished")