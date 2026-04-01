# -*- coding: utf-8 -*-
"""Shared hardware port-resolution helpers and calibration notes.

This module is *not* the runtime orchestrator, but is used by runtime entry
points to resolve lick sensor and reward valve channel selections from config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LickPortSelection:
    lick_input_name: str
    reward_output_name: str
    lick_input_type: str  # "analog" | "digital"
    reward_output_type: str  # "analog" | "digital"


def resolve_lick_ports(config: dict[str, Any]) -> LickPortSelection:
    """Resolve lick input + reward output logical names/types.

    Priority:
    1) `session.lick_input_name` and `session.reward_output_name`
    2) fallback legacy defaults: "lick", "reward"
    """
    session = config.get("session", {})
    channels = config.get("channels", {})

    lick_name = str(session.get("lick_input_name", "lick"))
    reward_name = str(session.get("reward_output_name", "reward"))

    analog_inputs = channels.get("analog_inputs", {}) or {}
    digital_inputs = channels.get("digital_inputs", {}) or {}
    analog_outputs = channels.get("analog_outputs", {}) or {}
    digital_outputs = channels.get("digital_outputs", {}) or {}

    if lick_name in analog_inputs:
        lick_type = "analog"
    elif lick_name in digital_inputs:
        lick_type = "digital"
    else:
        raise KeyError(
            f"Configured lick input '{lick_name}' was not found in channels.analog_inputs or channels.digital_inputs"
        )

    if reward_name in analog_outputs:
        reward_type = "analog"
    elif reward_name in digital_outputs:
        reward_type = "digital"
    else:
        raise KeyError(
            f"Configured reward output '{reward_name}' was not found in channels.analog_outputs or channels.digital_outputs"
        )

    return LickPortSelection(
        lick_input_name=lick_name,
        reward_output_name=reward_name,
        lick_input_type=lick_type,
        reward_output_type=reward_type,
    )

if __name__ == "__main__":
    raise SystemExit(
        "system_control.py provides shared helpers and calibration/prototyping notes. "
        "Use run_experiment.py or main_pipeline.py as the runtime orchestrator."
    )
