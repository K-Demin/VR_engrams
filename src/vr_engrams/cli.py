from __future__ import annotations

import argparse
from pathlib import Path

from .config_v2 import load_experiment_v2_config
from .daq_controller import DaqController
from .lick_detector import LickDetector
from .logger import ExperimentLogger
from .scheduler import ExperimentScheduler
from .stimulus_controller import StimulusController


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run VR Engrams experiment (v2 architecture)")
    parser.add_argument("config", help="Path to experiment_v2 YAML config")
    parser.add_argument("--animal-id", required=True, help="Animal identifier")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    config = load_experiment_v2_config(args.config)

    logger = ExperimentLogger(
        root_dir=Path(config["logging"]["output_root"]),
        animal_id=args.animal_id,
        config=config,
        run_name=config["session"].get("name", "vr_engrams_v2"),
    )

    daq = DaqController(enabled=bool(config["daq"]["enabled"]))

    for logical_name, channel in config["channels"]["digital_outputs"].items():
        daq.create_digital_output(logical_name, channel)
    for logical_name, channel in config["channels"]["digital_inputs"].items():
        daq.create_digital_input(logical_name, channel)

    if config["channels"].get("counter_outputs"):
        logger.log_event(
            "counter_outputs_declared_but_not_configured",
            counter_outputs=config["channels"]["counter_outputs"],
        )

    stimuli = StimulusController(daq=daq, logger=logger)

    def reward_callback() -> None:
        stimuli.deliver_puff(
            channel=config["session"]["reward_output_name"],
            duration_sec=float(config["stimuli"]["whisker"].get("duration_sec", 0.05)),
        )

    lick_detector = LickDetector(
        daq=daq,
        logger=logger,
        lick_input_name=config["session"]["lick_input_name"],
        reward_callback=reward_callback,
        poll_interval_sec=float(config["session"].get("lick_poll_interval_sec", 0.005)),
    )

    scheduler = ExperimentScheduler(config=config, stimuli=stimuli, logger=logger, lick_detector=lick_detector)

    try:
        lick_detector.start(reward_on_lick=bool(config["session"].get("reward_on_lick", False)))
        scheduler.run_all_phases()
    finally:
        lick_detector.stop()
        daq.close()
        logger.close()


if __name__ == "__main__":
    main()
