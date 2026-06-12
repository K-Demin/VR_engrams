from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigValidationError(ValueError):
    """Raised when experiment_v2 config is missing required fields."""


def load_experiment_v2_config(config_path: str | Path) -> dict[str, Any]:
    """Load and validate an experiment_v2 YAML config."""
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    validate_experiment_v2_config(config, source=str(path))
    return config


def validate_experiment_v2_config(config: dict[str, Any], source: str = "config") -> None:
    """Validate required experiment_v2 schema and fail fast with explicit errors."""
    errors: list[str] = []

    required_top = [
        "daq",
        "channels",
        "stimuli",
        "phases",
        "randomization",
        "logging",
        "session",
    ]
    _require_mapping(config, "$", errors)
    _require_keys(config, "$", required_top, errors)

    daq = config.get("daq", {})
    _require_mapping(daq, "daq", errors)
    _require_keys(daq, "daq", ["enabled"], errors)
    opto_mode = str(daq.get("opto_mode", "arduino")).lower()
    if opto_mode not in {"arduino", "counter", "dio"}:
        errors.append("Invalid value for 'daq.opto_mode': expected one of 'arduino', 'counter', 'dio'")

    channels = config.get("channels", {})
    _require_mapping(channels, "channels", errors)
    _require_keys(channels, "channels", ["digital_outputs", "digital_inputs"], errors)
    _require_mapping(channels.get("digital_outputs", {}), "channels.digital_outputs", errors)
    _require_mapping(channels.get("digital_inputs", {}), "channels.digital_inputs", errors)
    if "analog_outputs" in channels:
        _require_mapping(channels.get("analog_outputs"), "channels.analog_outputs", errors)
    if "analog_inputs" in channels:
        _require_mapping(channels.get("analog_inputs"), "channels.analog_inputs", errors)
    if "counter_outputs" in channels:
        _require_mapping(channels.get("counter_outputs"), "channels.counter_outputs", errors)

    stimuli = config.get("stimuli", {})
    _require_mapping(stimuli, "stimuli", errors)
    _require_keys(stimuli, "stimuli", ["audio", "visual", "whisker", "shock", "opto"], errors)
    for section in ["audio", "visual", "whisker", "shock", "opto"]:
        _require_mapping(stimuli.get(section, {}), f"stimuli.{section}", errors)

    phases = config.get("phases", {})
    _require_mapping(phases, "phases", errors)

    randomization = config.get("randomization", {})
    _require_mapping(randomization, "randomization", errors)
    dropout = randomization.get("dropout", {})
    if dropout:
        _require_mapping(dropout, "randomization.dropout", errors)
        _require_keys(
            dropout,
            "randomization.dropout",
            ["enabled", "interval_sec", "dropped_modalities", "dropout_duration_sec", "allow_multiple_simultaneous_drops"],
            errors,
        )

    logging_cfg = config.get("logging", {})
    _require_mapping(logging_cfg, "logging", errors)
    _require_keys(logging_cfg, "logging", ["output_root"], errors)

    session = config.get("session", {})
    _require_mapping(session, "session", errors)
    _require_keys(session, "session", ["name", "lick_input_name", "reward_output_name"], errors)

    _validate_phase_blocks(phases, errors)
    _validate_device_names(config, errors)
    _validate_imaging_config(config, errors)
    _validate_background_config(config, errors)

    if errors:
        message = f"Invalid experiment_v2 config ({source}):\n- " + "\n- ".join(errors)
        raise ConfigValidationError(message)


def _require_keys(mapping: Any, path: str, keys: list[str], errors: list[str]) -> None:
    if not isinstance(mapping, dict):
        return
    for key in keys:
        if key not in mapping:
            errors.append(f"Missing required key '{path}.{key}'")


def _require_mapping(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"Expected mapping at '{path}', got {type(value).__name__}")


def _validate_phase_blocks(phases: dict[str, Any], errors: list[str]) -> None:
    phase_key_map = {
        "decoder": "decoder",
        "pre-conditioning": "pre",
        "fear conditioning": "fear",
        "post-conditioning": "post",
        "fMRI opto block design": "fmri",
    }
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_cfg in phases.items():
        canonical = phase_key_map.get(raw_key, raw_key)
        if isinstance(raw_cfg, dict):
            normalized[canonical] = raw_cfg

    decoder = normalized.get("decoder")
    if decoder:
        _require_keys(decoder, "phases.decoder", ["conditions", "reps_per_condition", "event_duration_sec", "iti_sec"], errors)

    pre = normalized.get("pre")
    if pre:
        _require_keys(pre, "phases.pre-conditioning", ["blocks_per_condition", "block_table"], errors)

    fear = normalized.get("fear")
    if fear:
        _require_keys(
            fear,
            "phases.fear conditioning",
            ["shock_enabled", "target_scene_duration_min", "shocks_per_session", "shock_spacing_sec", "shock_channel"],
            errors,
        )

    post = normalized.get("post")
    if post:
        _require_keys(post, "phases.post-conditioning", ["blocks_per_condition", "block_table"], errors)

    fmri = normalized.get("fmri")
    if fmri:
        _require_keys(fmri, "phases.fMRI opto block design", ["total_duration_sec", "on_duration_sec", "off_duration_sec"], errors)


def _validate_device_names(config: dict[str, Any], errors: list[str]) -> None:
    channels = config.get("channels", {})
    if not isinstance(channels, dict):
        return

    digital_outputs = channels.get("digital_outputs", {}) if isinstance(channels.get("digital_outputs", {}), dict) else {}
    analog_outputs = channels.get("analog_outputs", {}) if isinstance(channels.get("analog_outputs", {}), dict) else {}
    digital_inputs = channels.get("digital_inputs", {}) if isinstance(channels.get("digital_inputs", {}), dict) else {}
    analog_inputs = channels.get("analog_inputs", {}) if isinstance(channels.get("analog_inputs", {}), dict) else {}
    counter_outputs = channels.get("counter_outputs", {}) if isinstance(channels.get("counter_outputs", {}), dict) else {}
    outputs = set(digital_outputs) | set(analog_outputs)
    inputs = set(digital_inputs) | set(analog_inputs)
    _validate_unique_channels("channels.digital_outputs", digital_outputs, errors)
    _validate_unique_channels("channels.analog_outputs", analog_outputs, errors)
    _validate_unique_channels("channels.digital_inputs", digital_inputs, errors)
    _validate_unique_channels("channels.analog_inputs", analog_inputs, errors)

    session = config.get("session", {}) if isinstance(config.get("session", {}), dict) else {}
    lick_input_name = session.get("lick_input_name")
    if lick_input_name and lick_input_name not in inputs:
        errors.append(
            f"Configured lick input '{lick_input_name}' is not defined in channels.analog_inputs or channels.digital_inputs"
        )
    if lick_input_name in analog_inputs and "lick_logic_mode" not in session:
        errors.append("Analog lick input is configured, but session.lick_logic_mode is missing")

    reward_output_name = session.get("reward_output_name")
    if reward_output_name and reward_output_name not in outputs:
        errors.append(
            f"Configured reward output '{reward_output_name}' is not defined in channels.analog_outputs or channels.digital_outputs"
        )

    stimuli = config.get("stimuli", {}) if isinstance(config.get("stimuli", {}), dict) else {}
    whisker_cfg = stimuli.get("whisker", {}) if isinstance(stimuli.get("whisker", {}), dict) else {}
    for key in ("output_name",):
        output_name = whisker_cfg.get(key)
        if output_name and output_name not in outputs:
            errors.append(f"Configured whisker output '{output_name}' from stimuli.whisker.{key} is not defined in output channels")
    side_selector_output = whisker_cfg.get("side_selector_output_name")
    if side_selector_output and side_selector_output not in digital_outputs:
        errors.append(
            f"Configured whisker selector '{side_selector_output}' from stimuli.whisker.side_selector_output_name is not defined in channels.digital_outputs"
        )
    for frequency_key in ("frequency_hz", "puff_a_frequency_hz", "puff_b_frequency_hz"):
        if frequency_key in whisker_cfg and float(whisker_cfg[frequency_key]) <= 0:
            errors.append(f"stimuli.whisker.{frequency_key} must be > 0 Hz")
    for duration_key in ("duration_sec", "puff_a_duration_sec", "puff_b_duration_sec"):
        if duration_key in whisker_cfg and float(whisker_cfg[duration_key]) <= 0:
            errors.append(f"stimuli.whisker.{duration_key} must be > 0 sec")

    opto_cfg = stimuli.get("opto", {}) if isinstance(stimuli.get("opto", {}), dict) else {}
    opto_output = opto_cfg.get("output_name", "opto")
    opto_mode = str(config.get("daq", {}).get("opto_mode", "arduino")).lower() if isinstance(config.get("daq", {}), dict) else "arduino"
    if opto_mode == "dio" and opto_output not in outputs:
        errors.append(f"Configured opto output '{opto_output}' is not defined in output channels")
    if opto_mode == "counter":
        counter_name = channels.get("counter_outputs", {}).get("laser_clock") if isinstance(channels.get("counter_outputs", {}), dict) else None
        if not counter_name and "laser_clock" not in counter_outputs:
            errors.append("daq.opto_mode='counter' requires channels.counter_outputs.laser_clock")

    phases = _normalized_phases(config.get("phases", {}))
    decoder = phases.get("decoder", {})
    if _phase_enabled(decoder):
        for condition in decoder.get("conditions", []):
            if "whisker" in str(condition):
                whisker_output = whisker_cfg.get("output_name", "puff")
                if whisker_output not in outputs:
                    errors.append(f"Decoder whisker condition requires output '{whisker_output}' in channels")
                if str(condition).endswith("_b") and side_selector_output and side_selector_output not in digital_outputs:
                    errors.append(f"Decoder whisker_b condition requires selector output '{side_selector_output}' in channels.digital_outputs")

    fear = phases.get("fear", {})
    if _phase_enabled(fear) and bool(fear.get("shock_enabled", False)):
        shock_channel = fear.get("shock_channel", stimuli.get("shock", {}).get("output_name", "shock") if isinstance(stimuli.get("shock", {}), dict) else "shock")
        if shock_channel not in outputs:
            errors.append(f"Fear conditioning requires shock output '{shock_channel}' in channels")

    fmri = phases.get("fmri", {})
    if _phase_enabled(fmri):
        fmri_opto = fmri.get("opto_channel", opto_output)
        if opto_mode == "dio" and fmri_opto not in outputs:
            errors.append(f"fMRI opto block design requires opto output '{fmri_opto}' in channels")

    imaging = config.get("imaging", {}) if isinstance(config.get("imaging", {}), dict) else {}
    ir_led_output = imaging.get("ir_led_output_name")
    if ir_led_output and ir_led_output not in digital_outputs:
        errors.append(f"Configured IR LED output '{ir_led_output}' is not defined in channels.digital_outputs")


def _validate_imaging_config(config: dict[str, Any], errors: list[str]) -> None:
    imaging = config.get("imaging", {})
    if imaging in (None, {}):
        return
    _require_mapping(imaging, "imaging", errors)
    if not isinstance(imaging, dict):
        return

    if not bool(imaging.get("enabled", False)):
        return

    _require_keys(imaging, "imaging", ["pc1_host", "pc1_port", "led_cycle", "frame_rate"], errors)
    session = config.get("session", {}) if isinstance(config.get("session", {}), dict) else {}
    _require_keys(session, "session", ["session_num", "run_num", "task_label"], errors)


def _validate_background_config(config: dict[str, Any], errors: list[str]) -> None:
    if "background" not in config:
        return

    background = config.get("background", {})
    _require_mapping(background, "background", errors)
    if not isinstance(background, dict):
        return

    if "duration_sec" in background and float(background["duration_sec"]) < 0:
        errors.append("background.duration_sec must be >= 0")


def _normalized_phases(phases: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(phases, dict):
        return {}

    phase_key_map = {
        "decoder": "decoder",
        "pre-conditioning": "pre",
        "fear conditioning": "fear",
        "post-conditioning": "post",
        "fMRI opto block design": "fmri",
    }
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_cfg in phases.items():
        canonical = phase_key_map.get(raw_key, raw_key)
        if isinstance(raw_cfg, dict):
            normalized[canonical] = raw_cfg
    return normalized


def _phase_enabled(phase_cfg: Any) -> bool:
    return isinstance(phase_cfg, dict) and bool(phase_cfg.get("enabled", True))


def _validate_unique_channels(path: str, channels: dict[str, Any], errors: list[str]) -> None:
    seen: dict[str, str] = {}
    for logical_name, raw_channel in channels.items():
        channel = str(raw_channel).strip().lower()
        if not channel:
            continue
        if channel in seen:
            errors.append(
                f"Duplicate physical output channel in {path}: '{logical_name}' and '{seen[channel]}' both use '{raw_channel}'"
            )
        else:
            seen[channel] = str(logical_name)
