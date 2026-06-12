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
        opto_mode = str(getattr(self.daq, "opto_mode", "arduino") or "arduino").strip().lower()
        startup_summary: dict[str, Any] = {
            "daq_enabled": self.daq.enabled,
            "digital_output_names": configured_outputs,
            "opto_counter_channel": self.daq.opto_counter_channel,
            "timing_policy": {
                "shock": {"preferred_path": "on_demand", "allow_software_fallback": self.daq.allow_software_fallback},
                "opto": {
                    "preferred_path": opto_mode,
                    "allow_software_fallback": False,
                    "frequency_hz": self.daq.opto_freq_hz,
                    "pulse_width_s": self.daq.opto_pulse_width_s,
                    "arduino_port": getattr(self.daq, "opto_arduino_port", None),
                    "arduino_pin": getattr(self.daq, "opto_arduino_pin", None),
                    "arduino_active_low": getattr(self.daq, "opto_arduino_active_low", None),
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

    def deliver_sound(self, frequency_hz: float, duration_sec: float, side: str = "both", block: bool = True) -> None:
        expected_backend = None
        if self.audio_engine is not None and bool(getattr(self.audio_engine, "enabled", True)):
            expected_backend = getattr(self.audio_engine, "active_backend", None)
        self.logger.log_event(
            "stim_sound",
            frequency_hz=frequency_hz,
            duration_sec=duration_sec,
            side=side,
            block=block,
            backend=expected_backend or "sleep_fallback",
            audio_init_error=(self.audio_engine.init_error if self.audio_engine is not None else "audio_engine_not_configured"),
        )

        backend: str | None = None
        if self.audio_engine is not None:
            backend = self.audio_engine.play_tone(frequency_hz=frequency_hz, duration_sec=duration_sec, side=side, block=block)
        if backend is not None and backend != expected_backend:
            self.logger.log_event("stim_sound_backend", backend=backend, expected_backend=expected_backend)
        if backend is None:
            time.sleep(duration_sec)

    def deliver_puff(
        self,
        channel: str,
        duration_sec: float,
        selector_channel: str | None = None,
        selector_state: bool | None = None,
        selector_settle_sec: float = 0.0,
        selector_hold_after_sec: float = 0.0,
        reset_selector_state: bool | None = None,
    ) -> None:
        if selector_channel is not None and selector_state is not None:
            self.daq.write_output(selector_channel, bool(selector_state))
            self.logger.log_event(
                "stim_puff_selector",
                selector_channel=selector_channel,
                selector_state=bool(selector_state),
                selector_settle_sec=selector_settle_sec,
            )
            if selector_settle_sec > 0:
                time.sleep(selector_settle_sec)

        try:
            path = self.daq.trigger_puff(channel, duration_sec)
            self.logger.log_event(
                "stim_puff",
                channel=channel,
                duration_sec=duration_sec,
                path=path,
                selector_channel=selector_channel,
                selector_state=selector_state,
            )
        finally:
            if selector_channel is not None and reset_selector_state is not None:
                if selector_hold_after_sec > 0:
                    time.sleep(selector_hold_after_sec)
                self.daq.write_output(selector_channel, bool(reset_selector_state))
                self.logger.log_event(
                    "stim_puff_selector_reset",
                    selector_channel=selector_channel,
                    selector_state=bool(reset_selector_state),
                    selector_hold_after_sec=selector_hold_after_sec,
                )

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
        if (self.daq.opto_mode or "arduino").strip().lower() == "counter" and not self.daq.opto_counter_channel:
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
