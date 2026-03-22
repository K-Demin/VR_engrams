from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from assignment import assign_target_scene

from .config_v2 import load_experiment_v2_config
from .audio_engine import AudioEngine
from .daq_controller import DaqController
from .lick_detector import LickDetector
from .logger import ExperimentLogger
from .scheduler import ExperimentScheduler
from .stimulus_controller import StimulusController
from .visual_engine import VisualEngine


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run VR Engrams experiment (v2 architecture)")
    parser.add_argument("config", help="Path to experiment_v2 YAML config")
    parser.add_argument("--animal-id", required=True, help="Animal identifier")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    config = load_experiment_v2_config(args.config)

    randomization_cfg = dict(config.get("randomization", {}))
    strategy = randomization_cfg.get("strategy", "deterministic_hash")
    seed = randomization_cfg.get("seed")
    allowed_scenes = list(randomization_cfg.get("allowed_scenes") or randomization_cfg.get("scene_pair") or ["A", "B"])

    target_scene = assign_target_scene(
        mouse_id=args.animal_id,
        strategy=strategy,
        seed=seed,
        allowed=allowed_scenes,
    )
    distractor_scene = next((scene for scene in allowed_scenes if scene != target_scene), None)

    session_assignment = {
        "mouse_id": args.animal_id,
        "strategy": strategy,
        "seed": seed,
        "allowed_scenes": allowed_scenes,
        "target": target_scene,
        "distractor": distractor_scene,
        "assigned_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    logger = ExperimentLogger(
        root_dir=Path(config["logging"]["output_root"]),
        animal_id=args.animal_id,
        config=config,
        run_name=config["session"].get("name", "vr_engrams_v2"),
    )
    logger.log_event("session_assignment", **session_assignment)

    daq = DaqController(
        enabled=bool(config["daq"]["enabled"]),
        opto_mode=str(config.get("daq", {}).get("opto_mode", "dio")),
        opto_do_name=str(config["stimuli"]["opto"].get("output_name", "opto")),
        opto_counter_channel=config.get("channels", {}).get("counter_outputs", {}).get("laser_clock"),
        opto_freq_hz=float(config["stimuli"]["opto"].get("frequency_hz", 20.0)),
        opto_pulse_width_s=float(config["stimuli"]["opto"].get("pulse_width_sec", 0.015)),
    )

    for logical_name, channel in config["channels"]["digital_outputs"].items():
        daq.create_digital_output(logical_name, channel)
    for logical_name, channel in config["channels"]["digital_inputs"].items():
        daq.create_digital_input(logical_name, channel)

    if config["channels"].get("counter_outputs"):
        logger.log_event(
            "counter_outputs_configured",
            counter_outputs=config["channels"]["counter_outputs"],
        )

    audio_cfg = dict(config.get("stimuli", {}).get("audio", {}))
    visual_cfg = dict(config.get("stimuli", {}).get("visual", {}))
    audio_engine = AudioEngine(
        enabled=bool(audio_cfg.get("enabled", False)),
        samplerate=int(audio_cfg.get("samplerate_hz", 48_000)),
        device=audio_cfg.get("device"),
    )
    visual_engine = VisualEngine(
        enabled=bool(visual_cfg.get("use_psychopy", False)),
        screen_index=int(visual_cfg.get("screen_index", 1)),
        fullscreen=bool(visual_cfg.get("fullscreen", True)),
        width=int(visual_cfg.get("width", 1920)),
        height=int(visual_cfg.get("height", 1080)),
    )
    stimuli = StimulusController(daq=daq, logger=logger, audio_engine=audio_engine, visual_engine=visual_engine)

    def reward_callback() -> None:
        stimuli.trigger_reward_valve(
            channel=config["session"]["reward_output_name"],
            duration_sec=float(config["stimuli"].get("reward_valve", {}).get("duration_sec", 0.05)),
        )

    lick_detector = LickDetector(
        daq=daq,
        logger=logger,
        lick_input_name=config["session"]["lick_input_name"],
        reward_callback=reward_callback,
        poll_interval_sec=float(config["session"].get("lick_poll_interval_sec", 0.005)),
    )

    scheduler = ExperimentScheduler(
        config=config,
        stimuli=stimuli,
        logger=logger,
        lick_detector=lick_detector,
        session_assignment=session_assignment,
    )

    try:
        lick_detector.start(reward_on_lick=bool(config["session"].get("reward_on_lick", False)))
        scheduler.run_all_phases()
    finally:
        lick_detector.stop()
        if stimuli.audio_engine is not None:
            stimuli.audio_engine.stop()
        if stimuli.visual_engine is not None:
            stimuli.visual_engine.close()
        daq.close()
        logger.close()


if __name__ == "__main__":
    main()
