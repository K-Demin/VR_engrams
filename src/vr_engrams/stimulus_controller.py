from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .audio_engine import AudioEngine
from .daq_controller import DaqController
from .logger import ExperimentLogger
from .visual_engine import VisualEngine


@dataclass
class StimulusController:
    """Unified stimulus API: visual, sound, puff, shock, opto."""

    daq: DaqController
    logger: ExperimentLogger
    audio_engine: AudioEngine | None = None
    visual_engine: VisualEngine | None = None

    def __post_init__(self) -> None:
        self.log_startup_self_check()

    def log_startup_self_check(self) -> None:
        configured_outputs = sorted(self.daq.do_tasks.keys())
        startup_summary: dict[str, Any] = {
            "daq_enabled": self.daq.enabled,
            "digital_output_names": configured_outputs,
            "opto_counter_channel": self.daq.opto_counter_channel,
            "timing_policy": {
                "shock": {"preferred_path": "on_demand", "allow_software_fallback": self.daq.allow_software_fallback},
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
        if self.visual_engine is None:
            raise RuntimeError("VisualEngine is not configured; cannot render visual stimulus")

        presented = self.visual_engine.present(stimulus=channel, duration_sec=duration_sec)
        self.logger.log_event(
            "stim_visual_backend",
            channel=channel,
            duration_sec=duration_sec,
            backend="psychopy",
            presented=presented,
            enabled=self.visual_engine.enabled,
            init_error=self.visual_engine.init_error,
        )
        if not presented:
            raise RuntimeError(
                "Visual stimulus was not presented. "
                "Set stimuli.visual.use_psychopy=true and verify PsychoPy + display routing (screen_index)."
            )

    def deliver_sound(self, frequency_hz: float, duration_sec: float, side: str = "both") -> None:
        used_backend = False
        if self.audio_engine is not None:
            used_backend = self.audio_engine.play_tone(frequency_hz=frequency_hz, duration_sec=duration_sec, side=side)
        self.logger.log_event(
            "stim_sound",
            frequency_hz=frequency_hz,
            duration_sec=duration_sec,
            side=side,
            backend="sounddevice" if used_backend else "sleep_fallback",
        )
        if not used_backend:
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
        # channel retained for scheduler/config compatibility; DAQ selects mode by `daq.opto_mode`.
        if (self.daq.opto_mode or "dio").strip().lower() == "counter" and not self.daq.opto_counter_channel:
            raise ValueError("opto_counter_channel is required when daq.opto_mode='counter'")
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
