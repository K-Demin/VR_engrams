#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Allow direct script execution without package install.
REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from assignment import assign_target_scene
from system_control import resolve_lick_ports
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

    assignment_cfg = (
        config.get("randomization_constraints", {}).get("mouse_level_scene_assignment", {})
    )
    strategy = assignment_cfg.get("strategy", "deterministic_hash")
    allowed = assignment_cfg.get("target_scene_set", ["A", "B"])
    seed = assignment_cfg.get("seed")

    target_scene = assign_target_scene(
        mouse_id=args.animal_id,
        strategy=strategy,
        seed=seed,
        allowed=allowed,
    )
    distractor_scene = next((scene for scene in allowed if scene != target_scene), None)

    session_assignment = {
        "mouse_id": args.animal_id,
        "strategy": strategy,
        "seed": seed,
        "allowed_scenes": list(allowed),
        "target_scene": target_scene,
        "distractor_scene": distractor_scene,
        "assigned_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    config.setdefault("session_metadata", {})
    config["session_metadata"]["scene_assignment"] = session_assignment

    output_root = Path(config.get("output_root", "./data"))
    logger = ExperimentLogger(root_dir=output_root, animal_id=args.animal_id, config=config, run_name="vr_engrams")

    daq_cfg = config.get("daq", {})
    daq = DaqController(
        enabled=bool(daq_cfg.get("enabled", True)),
        do_sample_rate_hz=float(daq_cfg.get("do_sample_rate_hz", 10_000.0)),
        allow_software_fallback=bool(daq_cfg.get("allow_software_fallback", False)),
        opto_counter_channel=daq_cfg.get("opto_counter_channel"),
        opto_freq_hz=float(daq_cfg.get("opto_freq_hz", 20.0)),
        opto_pulse_width_s=float(daq_cfg.get("opto_pulse_width_s", 0.015)),
    )
    channels = config.get("channels", {})
    for logical_name, channel in channels.get("digital_outputs", {}).items():
        daq.create_digital_output(logical_name, channel)
    for logical_name, channel in channels.get("digital_inputs", {}).items():
        daq.create_digital_input(logical_name, channel)
    for logical_name, channel in channels.get("analog_outputs", {}).items():
        daq.create_analog_output(logical_name, channel)
    for logical_name, channel in channels.get("analog_inputs", {}).items():
        daq.create_analog_input(logical_name, channel)

    stimuli = StimulusController(daq=daq, logger=logger)

    lick_ports = resolve_lick_ports(config)
    reward_channel = lick_ports.reward_output_name
    reward_cfg = config.get("stimuli", {}).get("reward_valve", {})
    if "duration_ms" in reward_cfg:
        reward_duration = max(0.1, float(reward_cfg["duration_ms"])) / 1000.0
    else:
        reward_duration = float(reward_cfg.get("duration_sec", 0.05))

    def reward_callback() -> None:
        stimuli.trigger_reward_valve(reward_channel, reward_duration)

    lick_detector = LickDetector(
        daq=daq,
        logger=logger,
        lick_input_name=lick_ports.lick_input_name,
        reward_callback=reward_callback,
        poll_interval_sec=float(config.get("session", {}).get("lick_poll_interval_sec", 0.005)),
        threshold=float(config.get("session", {}).get("lick_threshold", 2.5)),
        logic_mode=str(config.get("session", {}).get("lick_logic_mode", "high_is_lick")),
        refractory_sec=float(config.get("session", {}).get("lick_refractory_sec", 0.05)),
    )

    scheduler = ExperimentScheduler(
        config=config,
        stimuli=stimuli,
        logger=logger,
        lick_detector=lick_detector,
        session_assignment=session_assignment,
    )

    reward_on_lick = bool(config.get("session", {}).get("reward_on_lick", False))

    try:
        logger.log_event("session_assignment", **session_assignment)
        lick_detector.start(reward_on_lick=reward_on_lick)
        scheduler.run_all_phases()
    finally:
        lick_detector.stop()
        daq.close()
        logger.close()


if __name__ == "__main__":
    main()
