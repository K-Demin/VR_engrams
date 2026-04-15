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
    if opto_mode != "arduino":
        errors.append("Invalid value for 'daq.opto_mode': expected 'arduino'")

    channels = config.get("channels", {})
    _require_mapping(channels, "channels", errors)
    _require_keys(channels, "channels", ["digital_outputs", "digital_inputs"], errors)
    _require_mapping(channels.get("digital_outputs", {}), "channels.digital_outputs", errors)
    _require_mapping(channels.get("digital_inputs", {}), "channels.digital_inputs", errors)
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
