from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from assignment import assign_target_scene
from system_control import resolve_lick_ports

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
    logging.basicConfig(
        level=getattr(logging, str(config.get("logging", {}).get("python_log_level", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

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
        console_echo=bool(config.get("logging", {}).get("console_echo", True)),
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
    for logical_name, channel in config["channels"].get("analog_outputs", {}).items():
        daq.create_analog_output(logical_name, channel)
    for logical_name, channel in config["channels"].get("analog_inputs", {}).items():
        daq.create_analog_input(logical_name, channel)

    if config["channels"].get("counter_outputs"):
        logger.log_event(
            "counter_outputs_configured",
            counter_outputs=config["channels"]["counter_outputs"],
        )

    audio_cfg = dict(config.get("stimuli", {}).get("audio", {}))
    visual_cfg = dict(config.get("stimuli", {}).get("visual", {}))
    audio_engine = AudioEngine(
        enabled=bool(audio_cfg.get("enabled", True)),
        samplerate=int(audio_cfg.get("samplerate_hz", 48_000)),
        device=audio_cfg.get("device"),
    )
    screen_indices = visual_cfg.get("screen_indices")
    normalized_screen_indices = [int(idx) for idx in screen_indices] if isinstance(screen_indices, list) else None
    visual_engine = VisualEngine(
        enabled=bool(visual_cfg.get("use_psychopy", False)),
        screen_index=int(visual_cfg.get("screen_index", 1)),
        screen_indices=normalized_screen_indices,
        fullscreen=bool(visual_cfg.get("fullscreen", True)),
        width=int(visual_cfg.get("width", 1920)),
        height=int(visual_cfg.get("height", 1080)),
    )
    stimuli = StimulusController(
        daq=daq,
        logger=logger,
        audio_engine=audio_engine,
        visual_engine=visual_engine,
    )
    if not visual_engine.enabled:
        raise RuntimeError(
            "Visual backend is not ready for v2 runs. "
            f"init_error={visual_engine.init_error}. "
            "Set stimuli.visual.use_psychopy=true and verify PsychoPy installation and screen_index."
        )

    lick_ports = resolve_lick_ports(config)
    reward_cfg = config.get("stimuli", {}).get("reward_valve", {})
    if "duration_ms" in reward_cfg:
        reward_duration_sec = max(0.1, float(reward_cfg["duration_ms"])) / 1000.0
    else:
        reward_duration_sec = float(reward_cfg.get("duration_sec", 0.05))

    def reward_callback() -> None:
        stimuli.trigger_reward_valve(
            channel=lick_ports.reward_output_name,
            duration_sec=reward_duration_sec,
        )

    lick_detector = LickDetector(
        daq=daq,
        logger=logger,
        lick_input_name=lick_ports.lick_input_name,
        reward_callback=reward_callback,
        poll_interval_sec=float(config["session"].get("lick_poll_interval_sec", 0.005)),
        threshold=float(config["session"].get("lick_threshold", 2.5)),
        logic_mode=str(config["session"].get("lick_logic_mode", "high_is_lick")),
        refractory_sec=float(config["session"].get("lick_refractory_sec", 0.05)),
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
