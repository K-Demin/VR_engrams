from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .daq_controller import DaqController
from .logger import ExperimentLogger


@dataclass
class StimulusController:
    """Unified stimulus API: visual, sound, puff, shock, opto."""

    daq: DaqController
    logger: ExperimentLogger

    def __post_init__(self) -> None:
        self.log_startup_self_check()

    def log_startup_self_check(self) -> None:
        configured_outputs = sorted(self.daq.do_tasks.keys())
        startup_summary: dict[str, Any] = {
            "daq_enabled": self.daq.enabled,
            "digital_output_names": configured_outputs,
            "opto_counter_channel": self.daq.opto_counter_channel,
            "timing_policy": {
                "shock": {"preferred_path": "hardware_timed", "allow_software_fallback": self.daq.allow_software_fallback},
                "opto": {
                    "preferred_path": "hardware_timed_counter",
                    "allow_software_fallback": False,
                    "frequency_hz": self.daq.opto_freq_hz,
                    "pulse_width_s": self.daq.opto_pulse_width_s,
                },
            },
        }
        self.logger.log_event("stimulus_startup_self_check", **startup_summary)

    def deliver_visual(self, channel: str, duration_sec: float) -> None:
        self.logger.log_event("stim_visual", channel=channel, duration_sec=duration_sec)
        path = self.daq.pulse_output(channel, duration_sec)
        self.logger.log_event("stim_visual_path", channel=channel, duration_sec=duration_sec, path=path)

    def deliver_sound(self, frequency_hz: float, duration_sec: float, side: str = "both") -> None:
        # Placeholder for true audio backend integration.
        self.logger.log_event(
            "stim_sound",
            frequency_hz=frequency_hz,
            duration_sec=duration_sec,
            side=side,
        )
        time.sleep(duration_sec)

    def deliver_puff(self, channel: str, duration_sec: float) -> None:
        path = self.daq.trigger_puff(channel, duration_sec)
        self.logger.log_event("stim_puff", channel=channel, duration_sec=duration_sec, path=path)

    def deliver_shock(self, channel: str, duration_sec: float, amplitude: float | None = None) -> None:
        path = self.daq.trigger_shock(channel, duration_sec)
        self.logger.log_event(
            "stim_shock",
            channel=channel,
            duration_sec=duration_sec,
            amplitude=amplitude,
            path=path,
        )

    def deliver_opto(self, channel: str, duration_sec: float, power_mw: float | None = None) -> None:
        # channel retained for compatibility with scheduler/config, but DAQ uses configured counter.
        if not self.daq.opto_counter_channel:
            raise ValueError("opto_counter_channel is required to deliver opto in opto phases")
        path = self.daq.start_opto_train(duration_sec)
        self.logger.log_event(
            "stim_opto",
            channel=channel,
            duration_sec=duration_sec,
            power_mw=power_mw,
            path=path,
        )

    def stop_opto(self) -> None:
        self.daq.stop_opto_train()
        self.logger.log_event("stim_opto_stop")

    def trigger_reward_valve(self, channel: str, duration_sec: float) -> None:
        path = self.daq.trigger_reward_valve(channel, duration_sec)
        self.logger.log_event("stim_reward_valve", channel=channel, duration_sec=duration_sec, path=path)
