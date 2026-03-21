# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:39:56 2026

@author: JoshB
"""
# python main_pipeline.py configs/experiment.yaml --animal m01

import argparse
import copy
import os
from datetime import datetime

import yaml

from hardware.audio_controller import AudioController
from hardware.lick_detector import LickDetector
from hardware.puff_controller import PuffController
from tasks.puff_task_fsm import PuffTaskFSM
from utils.camera_control import ping_camera, start_camera, stop_camera
from utils.trial_logger import TrialLogger


def _normalize_config(raw_config: dict, animal_id: str) -> dict:
    """
    Accept legacy config format and the new grouped experiment config format.
    Returns a runtime config compatible with existing task/hardware code.
    """
    if "stimulus_parameters" in raw_config:
        cfg = {
            "animal_id": animal_id,
            "session": {
                "n_trials": raw_config["phase_timings_counts"]["acquisition"]["n_trials"],
                "easy_trials": raw_config["randomization_constraints"]["audio_puff_pairing"]["easy_trials"],
            },
            "timing": {
                "baseline": raw_config["phase_timings_counts"]["baseline"]["duration_sec"],
                "iti_min": raw_config["phase_timings_counts"]["acquisition"]["iti_min_sec"],
                "iti_max": raw_config["phase_timings_counts"]["acquisition"]["iti_max_sec"],
                "audio_duration": raw_config["stimulus_parameters"]["audio"]["duration_sec"],
                "delay": raw_config["phase_timings_counts"]["acquisition"]["delay_sec"],
                "puff_duration": raw_config["stimulus_parameters"]["puff"]["duration_sec"],
                "response_window": raw_config["phase_timings_counts"]["acquisition"]["response_window_sec"],
                "timeout": raw_config["phase_timings_counts"]["acquisition"]["timeout_sec"],
            },
            "hardware": {
                "puff_channel": raw_config["hardware_channels"]["puff"]["ni_do_channel"],
                "lick_channel": raw_config["hardware_channels"]["lick_valve"]["lick_ni_di_channel"],
                "puff_side": raw_config["stimulus_parameters"]["puff"]["side"],
            },
            "audio": {
                "left_freq": raw_config["stimulus_parameters"]["audio"]["left_freq_hz"],
                "right_freq": raw_config["stimulus_parameters"]["audio"]["right_freq_hz"],
            },
            "base_path_pc2": raw_config["logging_session_metadata"]["storage"]["base_path_pc2"],
            "base_path_pc1": raw_config["logging_session_metadata"]["storage"]["base_path_pc1"],
            "runtime_source_config": copy.deepcopy(raw_config),
        }
        return cfg

    # Legacy config support
    cfg = copy.deepcopy(raw_config)
    cfg["animal_id"] = animal_id
    cfg["runtime_source_config"] = copy.deepcopy(raw_config)
    return cfg


# =======================================================
# CLI
# =======================================================
parser = argparse.ArgumentParser(description="Widefield Puff Task")
parser.add_argument("config", help="Path to config YAML")
parser.add_argument("--animal", required=True, help="Animal ID e.g. m01")
args = parser.parse_args()

# =======================================================
# Load config
# =======================================================
with open(args.config, encoding="utf-8") as f:
    raw_config = yaml.safe_load(f)

config = _normalize_config(raw_config=raw_config, animal_id=args.animal)

# =======================================================
# Session folder
# PC2 writes to Y:/ (mapped shared drive)
# PC1 writes to its local path — sent in the START command
# Both use the same subfolder structure so files are co-located
# =======================================================
BASE_PC2 = config.get("base_path_pc2", "Y:/")
BASE_PC1 = config.get("base_path_pc1", "C:/Users/User/Documents/Data/Josh_test/BehaviourData")

date_str = datetime.now().strftime("%Y-%m-%d")
time_str = datetime.now().strftime("%H-%M-%S")
subfolder = f"{args.animal}/{date_str}/puff_task_{time_str}"

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
puff = PuffController(config["hardware"]["puff_channel"])
lick = LickDetector(config["hardware"]["lick_channel"])
audio = AudioController()

# Save immutable snapshot of the full source config plus runtime overrides.
effective_config = copy.deepcopy(config.get("runtime_source_config", raw_config))
effective_config.setdefault("runtime_overrides", {})
effective_config["runtime_overrides"]["animal_id"] = args.animal
effective_config["runtime_overrides"]["config_path"] = args.config
effective_config["runtime_overrides"]["resolved_at_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

logger = TrialLogger(
    animal_id=args.animal,
    base_path=BASE_PC2,
    config=effective_config,
    session_path=session_path_pc2,
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
