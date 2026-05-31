# -*- coding: utf-8 -*-
"""
main_audio_lick_reward.py

Entry point for audio → lick → reward association task.

Usage:
    python main_audio_lick_reward.py configs/audio_lick_reward.yaml --animal m01 --level 1
    python main_audio_lick_reward.py configs/audio_lick_reward.yaml --animal m01 --level 2
    python main_audio_lick_reward.py configs/audio_lick_reward.yaml --animal m01 --level 3

--level overrides the level in the config file if provided.
"""

import sys
import os
import yaml
import argparse
from datetime import datetime

from hardware.water_valve import WaterValve
from hardware.lick_detector import LickDetector
from hardware.audio_controller import AudioController
from utils.trial_logger import TrialLogger
from tasks.audio_lick_reward_fsm import AudioLickRewardFSM

# =======================================================
# CLI
# =======================================================
parser = argparse.ArgumentParser(description="Audio-Lick-Reward Task")
parser.add_argument("config",                  help="Path to config YAML")
parser.add_argument("--animal", required=True, help="Animal ID e.g. m01")
parser.add_argument("--level",  type=int,      help="Override task level (1, 2, or 3)")
args = parser.parse_args()

# =======================================================
# Load config
# =======================================================
with open(args.config) as f:
    config = yaml.safe_load(f)

config["animal_id"] = args.animal
if args.level is not None:
    config["session"]["level"] = args.level
    print(f"Level overridden via CLI: {args.level}")

level = config["session"]["level"]
assert level in (1, 2, 3), f"Level must be 1, 2, or 3 — got {level}"

# =======================================================
# Session folder
# =======================================================
BASE_PC2 = config.get("base_path_pc2", "Y:/")

date_str  = datetime.now().strftime("%Y-%m-%d")
time_str  = datetime.now().strftime("%H-%M-%S")
subfolder = f"{args.animal}/{date_str}/audio_lick_L{level}_{time_str}"

session_path = f"{BASE_PC2.rstrip('/')}/{subfolder}"
os.makedirs(session_path, exist_ok=True)
print(f"Session folder: {session_path}")

# =======================================================
# Hardware setup
# =======================================================
print("Initialising hardware...")

lick = LickDetector(
    channel   = config["hardware"]["lick_channel"],
    mode      = config["hardware"].get("lick_mode", "digital"),
    threshold = config["hardware"].get("lick_threshold", 1.0)
)

valve = WaterValve(config["hardware"]["valve_channel"])
audio = AudioController()

logger = TrialLogger(
    animal_id    = args.animal,
    base_path    = BASE_PC2,
    config       = config,
    session_path = session_path
)

# =======================================================
# Task setup + run
# =======================================================
task = AudioLickRewardFSM(config, valve, lick, audio, logger)

try:
    logger.start_session()
    print("Running audio-lick-reward task...")
    task.run()
finally:
    lick.close()
    logger.close()
    print("Session finished")
