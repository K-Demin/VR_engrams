#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Allow direct script execution without package install.
REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from vr_engrams.daq_controller import DaqController
from vr_engrams.lick_detector import LickDetector
from vr_engrams.logger import ExperimentLogger
from vr_engrams.scheduler import ExperimentScheduler
from vr_engrams.stimulus_controller import StimulusController


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run VR Engrams multi-phase experiment")
    parser.add_argument("config", help="Path to experiment YAML config")
    parser.add_argument("--animal-id", required=True, help="Animal identifier")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    with open(args.config, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    output_root = Path(config.get("output_root", "./data"))
    logger = ExperimentLogger(root_dir=output_root, animal_id=args.animal_id, config=config, run_name="vr_engrams")

    daq = DaqController(enabled=bool(config.get("daq", {}).get("enabled", True)))
    channels = config.get("channels", {})
    for logical_name, channel in channels.get("digital_outputs", {}).items():
        daq.create_digital_output(logical_name, channel)
    for logical_name, channel in channels.get("digital_inputs", {}).items():
        daq.create_digital_input(logical_name, channel)

    stimuli = StimulusController(daq=daq, logger=logger)

    reward_channel = config.get("reward", {}).get("channel", "reward")
    reward_duration = float(config.get("reward", {}).get("duration_sec", 0.05))

    def reward_callback() -> None:
        stimuli.deliver_puff(reward_channel, reward_duration)

    lick_detector = LickDetector(
        daq=daq,
        logger=logger,
        lick_input_name=config.get("lick", {}).get("input_name", "lick"),
        reward_callback=reward_callback,
        poll_interval_sec=float(config.get("lick", {}).get("poll_interval_sec", 0.005)),
    )

    scheduler = ExperimentScheduler(config=config, stimuli=stimuli, logger=logger, lick_detector=lick_detector)

    reward_on_lick = bool(config.get("lick", {}).get("reward_on_lick", False))

    try:
        lick_detector.start(reward_on_lick=reward_on_lick)
        scheduler.run_all_phases()
    finally:
        lick_detector.stop()
        daq.close()
        logger.close()


if __name__ == "__main__":
    main()
