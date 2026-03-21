from __future__ import annotations

import time
from dataclasses import dataclass

from .daq_controller import DaqController
from .logger import ExperimentLogger


@dataclass
class StimulusController:
    """Unified stimulus API: visual, sound, puff, shock, opto."""

    daq: DaqController
    logger: ExperimentLogger

    def deliver_visual(self, channel: str, duration_sec: float) -> None:
        self.logger.log_event("stim_visual", channel=channel, duration_sec=duration_sec)
        self.daq.pulse_output(channel, duration_sec)

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
        self.logger.log_event("stim_puff", channel=channel, duration_sec=duration_sec)
        self.daq.pulse_output(channel, duration_sec)

    def deliver_shock(self, channel: str, duration_sec: float, amplitude: float | None = None) -> None:
        self.logger.log_event(
            "stim_shock",
            channel=channel,
            duration_sec=duration_sec,
            amplitude=amplitude,
        )
        self.daq.pulse_output(channel, duration_sec)

    def deliver_opto(self, channel: str, duration_sec: float, power_mw: float | None = None) -> None:
        self.logger.log_event(
            "stim_opto",
            channel=channel,
            duration_sec=duration_sec,
            power_mw=power_mw,
        )
        self.daq.pulse_output(channel, duration_sec)
