"""Optogenetic pulse train controller using NI counters.

Provides counter-generated square pulse train defaults:
- 20 Hz pulse train
- 15 ms pulse width (high time)

Optionally supports an external digital gate for pause-triggered output.
"""

from __future__ import annotations

from typing import Callable, Optional

import nidaqmx
from nidaqmx.constants import AcquisitionType, DigitalLevel, TriggerType


EventHook = Callable[[str, dict], None]


class OptoController:
    """Counter-based pulse train controller for optogenetic stimulation."""

    def __init__(
        self,
        counter_channel: str,
        *,
        frequency_hz: float = 20.0,
        pulse_width_ms: float = 15.0,
        external_gate_source: Optional[str] = None,
        event_hook: Optional[EventHook] = None,
    ):
        if pulse_width_ms <= 0:
            raise ValueError("pulse_width_ms must be positive")

        period_s = 1.0 / frequency_hz
        pulse_width_s = pulse_width_ms / 1000.0
        if pulse_width_s >= period_s:
            raise ValueError("pulse_width_ms must be less than pulse period")

        self.counter_channel = counter_channel
        self.frequency_hz = frequency_hz
        self.pulse_width_ms = pulse_width_ms
        self.external_gate_source = external_gate_source
        self._event_hook = event_hook

        low_time = period_s - pulse_width_s

        self._task = nidaqmx.Task()
        self._task.co_channels.add_co_pulse_chan_time(
            counter=self.counter_channel,
            high_time=pulse_width_s,
            low_time=low_time,
        )
        self._task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)

        if self.external_gate_source:
            pause = self._task.triggers.pause_trigger
            pause.trig_type = TriggerType.DIGITAL_LEVEL
            pause.dig_lvl_src = self.external_gate_source
            pause.dig_lvl_when = DigitalLevel.LOW

        self._running = False
        self._log(
            "opto_init",
            counter_channel=self.counter_channel,
            frequency_hz=self.frequency_hz,
            pulse_width_ms=self.pulse_width_ms,
            external_gate_source=self.external_gate_source,
        )

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._task.start()
        self._running = True
        self._log("opto_start")

    def stop(self) -> None:
        if not self._running:
            return
        self._task.stop()
        self._running = False
        self._log("opto_stop")

    def close(self) -> None:
        if self._running:
            self.stop()
        self._task.close()
        self._log("opto_close")

    def _log(self, event: str, **fields) -> None:
        if self._event_hook is not None:
            self._event_hook(event, fields)

