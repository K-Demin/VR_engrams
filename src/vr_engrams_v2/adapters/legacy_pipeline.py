from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from vr_engrams import DaqController, ExperimentLogger, LickDetector, StimulusController
from vr_engrams_v2.components.improved_lick_monitor import ImprovedLickMonitor
from vr_engrams_v2.interfaces import (
    IDaqController,
    IExperimentLogger,
    ILickMonitor,
    IStimulusController,
)


@dataclass
class LegacyDaqAdapter(IDaqController):
    """Expose legacy DAQ controller through the v2 protocol."""

    legacy: DaqController

    def pulse_output(self, name: str, duration_sec: float) -> None:
        self.legacy.pulse_output(name, duration_sec)

    def write_output(self, name: str, state: bool) -> None:
        self.legacy.write_output(name, state)

    def read_input(self, name: str) -> bool:
        return self.legacy.read_input(name)

    def close(self) -> None:
        self.legacy.close()


@dataclass
class LegacyStimulusAdapter(IStimulusController):
    """Expose legacy stimulus controller through the v2 protocol."""

    legacy: StimulusController

    def deliver_visual(self, channel: str, duration_sec: float) -> None:
        self.legacy.deliver_visual(channel, duration_sec)

    def deliver_sound(self, frequency_hz: float, duration_sec: float, side: str = "both") -> None:
        self.legacy.deliver_sound(frequency_hz, duration_sec, side=side)

    def deliver_puff(self, channel: str, duration_sec: float) -> None:
        self.legacy.deliver_puff(channel, duration_sec)

    def deliver_shock(self, channel: str, duration_sec: float, amplitude: float | None = None) -> None:
        self.legacy.deliver_shock(channel, duration_sec, amplitude=amplitude)

    def deliver_opto(self, channel: str, duration_sec: float, power_mw: float | None = None) -> None:
        self.legacy.deliver_opto(channel, duration_sec, power_mw=power_mw)


@dataclass
class LegacyLoggerAdapter(IExperimentLogger):
    """Expose legacy logger through the v2 protocol."""

    legacy: ExperimentLogger

    def snapshot_parameters(self) -> None:
        self.legacy.snapshot_parameters()

    def log_event(self, event: str, **fields: object) -> None:
        self.legacy.log_event(event, **fields)

    def close(self) -> None:
        self.legacy.close()


@dataclass
class LegacyLickMonitorAdapter(ILickMonitor):
    """Expose legacy lick detector through the v2 protocol."""

    legacy: LickDetector

    def start(self, reward_on_lick: bool = False) -> None:
        self.legacy.start(reward_on_lick=reward_on_lick)

    def stop(self) -> None:
        self.legacy.stop()


def build_improved_lick_monitor_for_legacy(
    daq: DaqController,
    logger: ExperimentLogger,
    lick_input_name: str,
    reward_callback: Callable[[], None] | None = None,
) -> ILickMonitor:
    """Factory usable from legacy pipeline to opt into improved monitor only."""

    return ImprovedLickMonitor(
        daq=LegacyDaqAdapter(daq),
        logger=LegacyLoggerAdapter(logger),
        lick_input_name=lick_input_name,
        reward_callback=reward_callback,
    )
