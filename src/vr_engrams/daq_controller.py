from __future__ import annotations

import importlib
import importlib.util
import logging
import time
from dataclasses import dataclass, field
from threading import Timer
from typing import Any


@dataclass
class DaqController:
    """NI-DAQ helper for digital pulses, opto trains, and digital input reads.

    Hardware-first policy:
    - shock/puff/reward valve pulses use hardware-timed finite digital waveform when possible.
    - opto train uses NI counter output (20 Hz, 15 ms defaults).
    - software fallback exists only if `allow_software_fallback` is True.
    """

    enabled: bool = True
    do_sample_rate_hz: float = 10_000.0
    allow_software_fallback: bool = False
    opto_counter_channel: str | None = None
    opto_freq_hz: float = 20.0
    opto_pulse_width_s: float = 0.015

    do_tasks: dict[str, Any] = field(default_factory=dict)
    di_tasks: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._nidaqmx = None
        self._acquisition_type = None
        self._level = None
        self._logger = logging.getLogger(__name__)

        self._opto_task: Any | None = None
        self._opto_stop_timer: Timer | None = None

        if importlib.util.find_spec("nidaqmx") is None:
            self.enabled = False
            self._logger.warning("nidaqmx unavailable; DAQ disabled")
            return

        self._nidaqmx = importlib.import_module("nidaqmx")
        constants = importlib.import_module("nidaqmx.constants")
        self._acquisition_type = constants.AcquisitionType
        self._level = constants.Level

    def create_digital_output(self, name: str, channel: str) -> None:
        if not self.enabled:
            return
        task = self._nidaqmx.Task(new_task_name=f"do_{name}")
        task.do_channels.add_do_chan(channel)
        self.do_tasks[name] = task

    def create_digital_input(self, name: str, channel: str) -> None:
        if not self.enabled:
            return
        task = self._nidaqmx.Task(new_task_name=f"di_{name}")
        task.di_channels.add_di_chan(channel)
        self.di_tasks[name] = task

    def pulse_output(self, name: str, duration_sec: float) -> str:
        """Backward-compatible pulse API now routed to hardware-first helper."""
        return self._pulse_named_output(name=name, duration_sec=duration_sec, event_name="generic")

    def trigger_puff(self, channel_or_name: str, duration_sec: float) -> str:
        return self._pulse_named_output(name=channel_or_name, duration_sec=duration_sec, event_name="puff")

    def trigger_shock(self, channel_or_name: str, duration_sec: float) -> str:
        return self._pulse_named_output(name=channel_or_name, duration_sec=duration_sec, event_name="shock")

    def trigger_reward_valve(self, channel_or_name: str, duration_sec: float) -> str:
        return self._pulse_named_output(name=channel_or_name, duration_sec=duration_sec, event_name="reward_valve")

    def _pulse_named_output(self, name: str, duration_sec: float, event_name: str) -> str:
        duration_sec = max(0.0001, float(duration_sec))

        if not self.enabled:
            time.sleep(duration_sec)
            self._logger.info("%s used fallback path=disabled_no_hardware", event_name)
            return "fallback_disabled_no_hardware"

        if name in self.do_tasks:
            task = self.do_tasks[name]
            channel = None
            if hasattr(task, "do_channels") and len(task.do_channels) > 0:
                channel = task.do_channels[0].name
            if channel is None:
                channel = name
            return self._pulse_do_channel(channel=channel, duration_sec=duration_sec, event_name=event_name, named_task=task)

        return self._pulse_do_channel(channel=name, duration_sec=duration_sec, event_name=event_name)

    def _pulse_do_channel(self, channel: str, duration_sec: float, event_name: str, named_task: Any | None = None) -> str:
        # Attempt hardware-timed finite digital waveform (2 samples).
        try:
            with self._nidaqmx.Task() as hw_task:
                hw_task.do_channels.add_do_chan(channel)
                samples = max(2, int(round(duration_sec * self.do_sample_rate_hz)) + 1)
                hw_task.timing.cfg_samp_clk_timing(
                    rate=self.do_sample_rate_hz,
                    sample_mode=self._acquisition_type.FINITE,
                    samps_per_chan=samples,
                )
                waveform = [True] * (samples - 1) + [False]
                hw_task.write(waveform, auto_start=False)
                hw_task.start()
                hw_task.wait_until_done(timeout=max(1.0, duration_sec + 0.5))

            if named_task is not None:
                named_task.write(False)
            self._logger.info("%s used hardware-timed path", event_name)
            return "hardware_timed"
        except Exception as exc:
            if not self.allow_software_fallback:
                self._logger.error(
                    "%s hardware-timed path failed and fallback disabled: %s",
                    event_name,
                    exc,
                )
                raise RuntimeError(
                    f"{event_name} pulse failed on hardware-timed path and allow_software_fallback=False"
                ) from exc

            self._logger.warning(
                "%s using software fallback path due to hardware-timed failure: %s",
                event_name,
                exc,
            )
            if named_task is not None:
                named_task.write(True)
                time.sleep(duration_sec)
                named_task.write(False)
            else:
                with self._nidaqmx.Task() as sw_task:
                    sw_task.do_channels.add_do_chan(channel)
                    sw_task.write(True)
                    time.sleep(duration_sec)
                    sw_task.write(False)
            return "fallback_software"

    def start_opto_train(self, duration_sec: float | None = None) -> str:
        if not self.enabled:
            if duration_sec is not None:
                time.sleep(duration_sec)
            self._logger.info("opto_train used fallback path=disabled_no_hardware")
            return "fallback_disabled_no_hardware"

        if not self.opto_counter_channel:
            raise ValueError("opto_counter_channel must be configured for counter-based opto train")

        self.stop_opto_train()

        period_s = 1.0 / float(self.opto_freq_hz)
        high_time_s = min(float(self.opto_pulse_width_s), period_s)
        low_time_s = max(period_s - high_time_s, 1e-6)

        self._opto_task = self._nidaqmx.Task(new_task_name="opto_train")
        self._opto_task.co_channels.add_co_pulse_chan_time(
            counter=self.opto_counter_channel,
            high_time=high_time_s,
            low_time=low_time_s,
            idle_state=self._level.LOW,
        )
        self._opto_task.timing.cfg_implicit_timing(sample_mode=self._acquisition_type.CONTINUOUS)
        self._opto_task.start()
        self._logger.info(
            "opto_train started with hardware counter path freq_hz=%s pulse_width_s=%s",
            self.opto_freq_hz,
            self.opto_pulse_width_s,
        )

        if duration_sec is not None:
            self._opto_stop_timer = Timer(float(duration_sec), self.stop_opto_train)
            self._opto_stop_timer.daemon = True
            self._opto_stop_timer.start()

        return "hardware_counter"

    def stop_opto_train(self) -> None:
        if self._opto_stop_timer is not None:
            self._opto_stop_timer.cancel()
            self._opto_stop_timer = None

        if self._opto_task is not None:
            try:
                self._opto_task.stop()
            except Exception:
                pass
            self._opto_task.close()
            self._opto_task = None
            self._logger.info("opto_train stopped")

    def write_output(self, name: str, state: bool) -> None:
        if self.enabled:
            self.do_tasks[name].write(state)

    def read_input(self, name: str) -> bool:
        if not self.enabled:
            return False
        return bool(self.di_tasks[name].read())

    def close(self) -> None:
        self.stop_opto_train()
        for task in list(self.do_tasks.values()) + list(self.di_tasks.values()):
            task.close()
        self.do_tasks.clear()
        self.di_tasks.clear()
