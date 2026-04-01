from __future__ import annotations

import importlib
import importlib.util
import logging
import time
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any


@dataclass
class DaqController:
    """NI-DAQ helper for digital pulses, opto trains, and digital input reads.

    Pulse policy:
    - shock/puff/reward valve pulses use OnDemand digital writes (Python-timed pulse width).
    - opto train uses NI counter output (20 Hz, 15 ms defaults).
    - software fallback exists only if `allow_software_fallback` is True.
    """

    enabled: bool = True
    do_sample_rate_hz: float = 10_000.0
    allow_software_fallback: bool = False
    opto_counter_channel: str | None = None
    opto_mode: str = "dio"
    opto_do_name: str = "opto"
    opto_freq_hz: float = 20.0
    opto_pulse_width_s: float = 0.015

    do_tasks: dict[str, Any] = field(default_factory=dict)
    di_tasks: dict[str, Any] = field(default_factory=dict)
    ao_tasks: dict[str, Any] = field(default_factory=dict)
    ai_tasks: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._nidaqmx = None
        self._acquisition_type = None
        self._level = None
        self._logger = logging.getLogger(__name__)

        self._opto_task: Any | None = None
        self._opto_do_stop_event = Event()
        self._opto_do_thread: Thread | None = None

        if not self.enabled:
            self._logger.info("DAQ disabled by config")
            return

        if importlib.util.find_spec("nidaqmx") is None:
            raise RuntimeError(
                "DAQ is enabled in config, but nidaqmx is not installed in this Python environment."
            )

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

    def create_analog_output(self, name: str, channel: str) -> None:
        if not self.enabled:
            return
        task = self._nidaqmx.Task(new_task_name=f"ao_{name}")
        task.ao_channels.add_ao_voltage_chan(channel)
        task.write(0.0)
        self.ao_tasks[name] = task

    def create_analog_input(self, name: str, channel: str) -> None:
        if not self.enabled:
            return
        task = self._nidaqmx.Task(new_task_name=f"ai_{name}")
        task.ai_channels.add_ai_voltage_chan(channel)
        self.ai_tasks[name] = task

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
            self._logger.info("%s pulse path=fallback_disabled_no_hardware", event_name)
            return "fallback_disabled_no_hardware"

        if name in self.do_tasks:
            task = self.do_tasks[name]
            channel = None
            if hasattr(task, "do_channels") and len(task.do_channels) > 0:
                channel = task.do_channels[0].name
            if channel is None:
                channel = name
            return self._pulse_do_channel(channel=channel, duration_sec=duration_sec, event_name=event_name, named_task=task)

        if name in self.ao_tasks:
            task = self.ao_tasks[name]
            return self._pulse_ao_channel(duration_sec=duration_sec, event_name=event_name, named_task=task)

        return self._pulse_do_channel(channel=name, duration_sec=duration_sec, event_name=event_name)

    def _pulse_ao_channel(self, duration_sec: float, event_name: str, named_task: Any) -> str:
        try:
            named_task.write(5.0)
            time.sleep(duration_sec)
            named_task.write(0.0)
            self._logger.info("%s pulse path=analog_on_demand duration_sec=%s", event_name, duration_sec)
            return "analog_on_demand"
        except Exception as exc:
            if not self.allow_software_fallback:
                raise RuntimeError(f"{event_name} pulse failed on analog output") from exc
            time.sleep(duration_sec)
            self._logger.warning("%s pulse path=fallback_disabled_no_hardware (analog failed=%s)", event_name, exc)
            return "fallback_disabled_no_hardware"

    def _pulse_do_channel(self, channel: str, duration_sec: float, event_name: str, named_task: Any | None = None) -> str:
        try:
            self._pulse_hardware_timed(channel=channel, duration_sec=duration_sec)
            self._logger.info("%s pulse path=hardware_timed channel=%s duration_sec=%s", event_name, channel, duration_sec)
            return "hardware_timed"
        except Exception as exc:
            try:
                self._pulse_on_demand(channel=channel, duration_sec=duration_sec, named_task=named_task)
                self._logger.info(
                    "%s pulse path=on_demand channel=%s duration_sec=%s (hardware_timed_failed=%s)",
                    event_name,
                    channel,
                    duration_sec,
                    exc,
                )
                return "on_demand"
            except Exception as on_demand_exc:
                if not self.allow_software_fallback:
                    self._logger.error(
                        "%s pulse paths=hardware_timed+on_demand_failed fallback=disabled errors=(%s, %s)",
                        event_name,
                        exc,
                        on_demand_exc,
                    )
                    raise RuntimeError(
                        f"{event_name} pulse failed on hardware-timed and on-demand paths with allow_software_fallback=False"
                    ) from on_demand_exc

                self._logger.warning(
                    "%s pulse paths=hardware_timed+on_demand_failed fallback=software error=%s",
                    event_name,
                    on_demand_exc,
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

    def _pulse_hardware_timed(self, channel: str, duration_sec: float) -> None:
        with self._nidaqmx.Task() as hw_task:
            hw_task.do_channels.add_do_chan(channel)
            hw_task.timing.cfg_samp_clk_timing(
                rate=self.do_sample_rate_hz,
                sample_mode=self._acquisition_type.FINITE,
                samps_per_chan=2,
            )
            hw_task.write([True, False], auto_start=False)
            hw_task.start()
            hw_task.wait_until_done(timeout=max(1.0, duration_sec + 0.5))

    def _pulse_on_demand(self, channel: str, duration_sec: float, named_task: Any | None = None) -> None:
        if named_task is not None:
            named_task.write(True)
            time.sleep(duration_sec)
            named_task.write(False)
            return
        with self._nidaqmx.Task() as sw_task:
            sw_task.do_channels.add_do_chan(channel)
            sw_task.write(True)
            time.sleep(duration_sec)
            sw_task.write(False)

    def start_opto_train(self, duration_sec: float | None = None) -> str:
        if not self.enabled:
            if duration_sec is not None:
                time.sleep(duration_sec)
            self._logger.info("opto_train path=fallback_disabled_no_hardware")
            return "fallback_disabled_no_hardware"

        self.stop_opto_train()
        mode = (self.opto_mode or "dio").strip().lower()
        if mode == "counter":
            if not self.opto_counter_channel:
                raise ValueError("opto_counter_channel must be configured for counter-based opto train")
            return self._start_opto_counter_train(duration_sec=duration_sec)
        return self._start_opto_dio_train(duration_sec=duration_sec)

    def _start_opto_counter_train(self, duration_sec: float | None) -> str:
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
            "opto_train path=hardware_timed_counter freq_hz=%s pulse_width_s=%s",
            self.opto_freq_hz,
            self.opto_pulse_width_s,
        )

        if duration_sec is not None:
            time.sleep(float(duration_sec))
            self.stop_opto_train()

        return "hardware_counter"

    def _start_opto_dio_train(self, duration_sec: float | None) -> str:
        if self.opto_do_name not in self.do_tasks:
            raise ValueError(f"opto DO output '{self.opto_do_name}' is not configured")

        self._opto_do_stop_event.clear()
        high_time_s = min(float(self.opto_pulse_width_s), 1.0 / float(self.opto_freq_hz))
        low_time_s = max((1.0 / float(self.opto_freq_hz)) - high_time_s, 1e-6)

        def _run_train(run_duration_sec: float | None) -> None:
            start_t = time.perf_counter()
            task = self.do_tasks[self.opto_do_name]
            while not self._opto_do_stop_event.is_set():
                if run_duration_sec is not None and (time.perf_counter() - start_t) >= run_duration_sec:
                    break
                task.write(True)
                time.sleep(high_time_s)
                task.write(False)
                time.sleep(low_time_s)
            task.write(False)

        if duration_sec is None:
            self._opto_do_thread = Thread(
                target=_run_train,
                kwargs={"run_duration_sec": None},
                daemon=True,
                name="OptoDOTrain",
            )
            self._opto_do_thread.start()
        else:
            _run_train(float(duration_sec))

        self._logger.info(
            "opto_train path=dio_train opto_do_name=%s freq_hz=%s pulse_width_s=%s",
            self.opto_do_name,
            self.opto_freq_hz,
            self.opto_pulse_width_s,
        )
        return "dio_train"

    def stop_opto_train(self) -> None:
        self._opto_do_stop_event.set()
        if self._opto_do_thread is not None:
            self._opto_do_thread.join(timeout=1.0)
            self._opto_do_thread = None
        if self.opto_do_name in self.do_tasks:
            try:
                self.do_tasks[self.opto_do_name].write(False)
            except Exception:
                pass

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

    def read_input(self, name: str) -> float | bool:
        if not self.enabled:
            return False
        if name in self.ai_tasks:
            return float(self.ai_tasks[name].read())
        return bool(self.di_tasks[name].read())

    def close(self) -> None:
        self.stop_opto_train()
        for task in list(self.do_tasks.values()) + list(self.di_tasks.values()) + list(self.ao_tasks.values()) + list(self.ai_tasks.values()):
            task.close()
        self.do_tasks.clear()
        self.di_tasks.clear()
        self.ao_tasks.clear()
        self.ai_tasks.clear()
