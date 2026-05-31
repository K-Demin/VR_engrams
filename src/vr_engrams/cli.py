from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assignment import assign_target_scene
from system_control import resolve_lick_ports

from .audio_engine import AudioEngine
from .bids import BIDSPath
from .camera_sync import CameraSyncClient
from .config_v2 import load_experiment_v2_config
from .daq_controller import DaqController
from .ir_sync import IRSyncController
from .lick_detector import LickDetector
from .logger import ExperimentLogger
from .scheduler import ExperimentScheduler
from .stimulus_controller import StimulusController
from .visual_engine import VisualEngine


PHASE_KEY_MAP = {
    "decoder": "decoder",
    "pre-conditioning": "pre",
    "fear conditioning": "fear",
    "post-conditioning": "post",
    "fMRI opto block design": "fmri",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run VR Engrams experiment (v2 architecture)")
    parser.add_argument("config", help="Path to experiment_v2 YAML config")
    parser.add_argument("--animal-id", required=True, help="Animal identifier")
    parser.add_argument("--session", type=int, help="BIDS/session number override")
    parser.add_argument("--run", type=int, help="BIDS/run number override")
    parser.add_argument("--no-camera-sync", action="store_true", help="Use local PC2 time and skip PC1 camera commands")
    return parser


def _apply_runtime_overrides(config: dict[str, Any], args: argparse.Namespace) -> None:
    session = config.setdefault("session", {})
    if args.session is not None:
        session["session_num"] = int(args.session)
    else:
        session.setdefault("session_num", 1)

    if args.run is not None:
        session["run_num"] = int(args.run)
    else:
        session.setdefault("run_num", 1)

    session.setdefault("task_label", session.get("name", "vrengrams"))

    config["runtime"] = {
        "animal_id": args.animal_id,
        "config_path": str(args.config),
        "session_num": int(session["session_num"]),
        "run_num": int(session["run_num"]),
        "task_label": str(session["task_label"]),
        "camera_sync_requested": bool(config.get("imaging", {}).get("enabled", False)),
        "camera_sync_enabled": _camera_sync_enabled(config, args),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "enabled_phases": _enabled_phase_names(config),
    }


def _camera_sync_enabled(config: dict[str, Any], args: argparse.Namespace) -> bool:
    imaging = config.get("imaging", {})
    return isinstance(imaging, dict) and bool(imaging.get("enabled", False)) and not bool(args.no_camera_sync)


def _enabled_phase_names(config: dict[str, Any]) -> list[str]:
    phases = config.get("phases", {})
    if not isinstance(phases, dict):
        return []
    return [str(name) for name, phase_cfg in phases.items() if not isinstance(phase_cfg, dict) or phase_cfg.get("enabled", True)]


def _enabled_canonical_phases(config: dict[str, Any]) -> set[str]:
    phases = config.get("phases", {})
    if not isinstance(phases, dict):
        return set()
    enabled: set[str] = set()
    for raw_name, phase_cfg in phases.items():
        if isinstance(phase_cfg, dict) and not phase_cfg.get("enabled", True):
            continue
        enabled.add(PHASE_KEY_MAP.get(str(raw_name), str(raw_name)))
    return enabled


def _visual_required(config: dict[str, Any]) -> bool:
    return bool(_enabled_canonical_phases(config) & {"decoder", "pre", "fear", "post"})


def _lick_monitor_required(config: dict[str, Any]) -> bool:
    session = config.get("session", {})
    if isinstance(session, dict) and "monitor_licks" in session:
        return bool(session["monitor_licks"])
    return bool(_enabled_canonical_phases(config) - {"fmri"})


def _build_bids_path(config: dict[str, Any], animal_id: str) -> BIDSPath:
    logging_cfg = config.get("logging", {})
    imaging_cfg = config.get("imaging", {})
    session = config.get("session", {})
    output_root = logging_cfg.get("output_root", "./data")
    project_root_pc2 = Path(logging_cfg.get("bids_root_pc2", output_root))
    project_root_pc1 = str(logging_cfg.get("bids_root_pc1", imaging_cfg.get("pc1_data_root", output_root)))
    return BIDSPath(
        project_root_pc2=project_root_pc2,
        project_root_pc1=project_root_pc1,
        sub=animal_id,
        ses=session.get("session_num", 1),
        task=str(session.get("task_label", session.get("name", "vrengrams"))),
        run=session.get("run_num", 1),
    )


def _normalise_led_cycle(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _start_camera_sync(
    config: dict[str, Any],
    logger: ExperimentLogger,
    bids_path: BIDSPath,
) -> tuple[CameraSyncClient, float]:
    imaging_cfg = config.get("imaging", {})
    client = CameraSyncClient(
        host=str(imaging_cfg["pc1_host"]),
        port=int(imaging_cfg["pc1_port"]),
        timeout_ping_sec=float(imaging_cfg.get("timeout_ping_sec", 5.0)),
        timeout_command_sec=float(imaging_cfg.get("timeout_command_sec", 20.0)),
    )
    if not client.ping():
        raise RuntimeError(f"Camera server at {client.host}:{client.port} did not respond to PING")

    clock_sync = client.measure_clock_offset(n_samples=int(imaging_cfg.get("timesync_samples", 5)))
    led_cycle = _normalise_led_cycle(imaging_cfg.get("led_cycle"))
    ok, imaging_start_unix = client.start(
        session_path_pc1=bids_path.func_dir_pc1,
        bids_stem=bids_path.filename(""),
        led_cycle=led_cycle,
    )
    if not ok or imaging_start_unix is None:
        raise RuntimeError("Camera server rejected START command")

    clock_sync.update(
        {
            "pc1_imaging_start_unix": imaging_start_unix,
            "pc1_imaging_start_timeofday": datetime.fromtimestamp(imaging_start_unix, tz=timezone.utc).isoformat(),
            "led_cycle": led_cycle,
            "frame_rate": float(imaging_cfg.get("frame_rate", 0.0)),
            "session_num": config["session"].get("session_num"),
            "run_num": config["session"].get("run_num"),
            "task_label": config["session"].get("task_label"),
        }
    )
    logger.update_clock_sync(clock_sync)
    return client, float(imaging_start_unix)


def _create_daq(config: dict[str, Any]) -> DaqController:
    daq = DaqController(
        enabled=bool(config["daq"]["enabled"]),
        opto_mode=str(config.get("daq", {}).get("opto_mode", "arduino")),
        opto_do_name=str(config["stimuli"]["opto"].get("output_name", "opto")),
        opto_counter_channel=config.get("channels", {}).get("counter_outputs", {}).get("laser_clock"),
        opto_freq_hz=float(config["stimuli"]["opto"].get("frequency_hz", 20.0)),
        opto_pulse_width_s=float(config["stimuli"]["opto"].get("pulse_width_sec", 0.015)),
        opto_arduino_port=str(config["stimuli"]["opto"].get("arduino_port", "COM3")),
        opto_arduino_baud=int(config["stimuli"]["opto"].get("arduino_baud", 115200)),
        opto_arduino_timeout_s=float(config["stimuli"]["opto"].get("arduino_timeout_sec", 1.0)),
    )

    for logical_name, channel in config["channels"]["digital_outputs"].items():
        daq.create_digital_output(logical_name, channel)
    for logical_name, channel in config["channels"]["digital_inputs"].items():
        daq.create_digital_input(logical_name, channel)
    for logical_name, channel in config["channels"].get("analog_outputs", {}).items():
        daq.create_analog_output(logical_name, channel)
    for logical_name, channel in config["channels"].get("analog_inputs", {}).items():
        daq.create_analog_input(logical_name, channel)
    return daq


def _reward_duration_sec(config: dict[str, Any]) -> float:
    reward_cfg = config.get("stimuli", {}).get("reward_valve", {})
    if "duration_ms" in reward_cfg:
        return max(0.0001, float(reward_cfg["duration_ms"]) / 1000.0)
    return max(0.0001, float(reward_cfg.get("duration_sec", 0.05)))


def main() -> None:
    args = _build_parser().parse_args()
    config = load_experiment_v2_config(args.config)
    _apply_runtime_overrides(config, args)
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

    camera_sync_enabled = _camera_sync_enabled(config, args)
    bids_path = _build_bids_path(config, args.animal_id) if camera_sync_enabled else None
    logger = ExperimentLogger(
        root_dir=Path(config["logging"]["output_root"]),
        animal_id=args.animal_id,
        config=config,
        run_name=config["session"].get("name", "vr_engrams_v2"),
        console_echo=bool(config.get("logging", {}).get("console_echo", True)),
        bids_path=bids_path,
    )

    daq = _create_daq(config)
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
    visual_required = _visual_required(config)
    if visual_required and not visual_engine.enabled:
        raise RuntimeError(
            "Visual backend is not ready for v2 runs. "
            f"init_error={visual_engine.init_error}. "
            "Set stimuli.visual.use_psychopy=true and verify PsychoPy installation and screen_index."
        )

    lick_ports = resolve_lick_ports(config)
    reward_duration_sec = _reward_duration_sec(config)

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

    camera_client: CameraSyncClient | None = None
    imaging_start_unix: float | None = None
    ir_sync = IRSyncController.from_config(daq=daq, logger=logger, config=config) if camera_sync_enabled else None
    lick_monitor_started = False

    try:
        if camera_sync_enabled:
            if bids_path is None:
                raise RuntimeError("Camera sync requested but BIDS path was not built")
            camera_client, imaging_start_unix = _start_camera_sync(config=config, logger=logger, bids_path=bids_path)

        logger.start_session(session_start_unix=imaging_start_unix)
        logger.log_event("session_assignment", **session_assignment)
        logger.log_event(
            "runtime_task_selection",
            enabled_phases=config.get("runtime", {}).get("enabled_phases", []),
            task_label=config["session"].get("task_label"),
            session_num=config["session"].get("session_num"),
            run_num=config["session"].get("run_num"),
            camera_sync_enabled=camera_sync_enabled,
        )

        if camera_sync_enabled:
            logger.log_event(
                "camera_sync_started",
                pc1_imaging_start_unix=imaging_start_unix,
                bids_func_dir_pc2=str(bids_path.func_dir_pc2) if bids_path else "",
                bids_func_dir_pc1=bids_path.func_dir_pc1 if bids_path else "",
                bids_stem=bids_path.filename("") if bids_path else "",
            )
            if ir_sync is not None:
                ir_sync.pulse("ir_sync_run_start", blocking=True)
                ir_sync.pulse("ir_sync_imaging_start", blocking=True)

        if _lick_monitor_required(config):
            lick_detector.start(reward_on_lick=bool(config["session"].get("reward_on_lick", False)))
            lick_monitor_started = True
        else:
            logger.log_event("lick_monitor_skipped", reason="not_required_for_enabled_phases")
        scheduler.run_all_phases()
    finally:
        if logger.session_started and ir_sync is not None:
            ir_sync.pulse("ir_sync_imaging_stop", blocking=True)
            ir_sync.pulse("ir_sync_run_end", blocking=True)
        if lick_monitor_started:
            lick_detector.stop()
        if camera_client is not None:
            try:
                logger.log_event("camera_sync_stop_requested")
                stopped = camera_client.stop()
                logger.log_event("camera_sync_stopped", ok=stopped)
            except Exception as exc:
                logger.log_event("camera_sync_stop_failed", error=str(exc))
        if stimuli.audio_engine is not None:
            stimuli.audio_engine.stop()
        if stimuli.visual_engine is not None:
            stimuli.visual_engine.close()
        daq.close()
        logger.close()


if __name__ == "__main__":
    main()
