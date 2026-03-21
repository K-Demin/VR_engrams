# -*- coding: utf-8 -*-
"""NI-DAQ helper for hardware-timed digital and counter outputs."""

from __future__ import annotations

import threading
import time
from typing import Optional

import nidaqmx
from nidaqmx.constants import AcquisitionType, Level


class DaqController:
    """Central DAQ output helper.

    Digital one-shot TTL:
      - Tries hardware-timed finite digital waveform first.
      - Falls back to software-timed line toggling if the device/line does not
        support hardware timing.

    Optogenetic train:
      - Uses NI counter output with fixed frequency and pulse width.
      - Hardware generates pulses; Python only starts/stops the task.
    """

    def __init__(
        self,
        do_sample_rate_hz: float = 10_000.0,
        opto_counter_channel: Optional[str] = None,
        opto_freq_hz: float = 20.0,
        opto_pulse_width_s: float = 0.015,
    ) -> None:
        self.do_sample_rate_hz = do_sample_rate_hz

        self.opto_counter_channel = opto_counter_channel
        self.opto_freq_hz = opto_freq_hz
        self.opto_pulse_width_s = opto_pulse_width_s

        self._opto_task: Optional[nidaqmx.Task] = None
        self._opto_stop_timer: Optional[threading.Timer] = None

    def pulse_digital_one_shot(self, line: str, pulse_s: float) -> None:
        """Deliver a one-shot TTL pulse on a digital line."""
        pulse_s = max(0.0001, float(pulse_s))

        # Prefer hardware-timed digital waveform (finite, 2 samples).
        try:
            with nidaqmx.Task() as task:
                task.do_channels.add_do_chan(line)
                task.timing.cfg_samp_clk_timing(
                    rate=self.do_sample_rate_hz,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=2,
                )
                task.write([True, False], auto_start=False)
                task.start()
                task.wait_until_done(timeout=max(1.0, pulse_s + 0.5))
            return
        except Exception:
            # Device/line likely software-timed only.
            pass

        # Software-timed fallback.
        with nidaqmx.Task() as task:
            task.do_channels.add_do_chan(line)
            task.write(False)
            time.sleep(0.001)
            task.write(True)
            time.sleep(pulse_s)
            task.write(False)

    def start_opto_train(self, duration_s: Optional[float] = None) -> None:
        """Start hardware-timed opto pulse train (20 Hz / 15 ms default)."""
        if not self.opto_counter_channel:
            raise ValueError("Opto counter channel is not configured.")

        self.stop_opto()

        period_s = 1.0 / self.opto_freq_hz
        high_time_s = min(self.opto_pulse_width_s, period_s)
        low_time_s = max(period_s - high_time_s, 1e-6)

        self._opto_task = nidaqmx.Task()
        self._opto_task.co_channels.add_co_pulse_chan_time(
            counter=self.opto_counter_channel,
            high_time=high_time_s,
            low_time=low_time_s,
            idle_state=Level.LOW,
        )
        self._opto_task.timing.cfg_implicit_timing(
            sample_mode=AcquisitionType.CONTINUOUS
        )
        self._opto_task.start()

        if duration_s is not None:
            self._opto_stop_timer = threading.Timer(float(duration_s), self.stop_opto)
            self._opto_stop_timer.daemon = True
            self._opto_stop_timer.start()

    def stop_opto(self) -> None:
        """Stop and close active opto counter task."""
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

    def close(self) -> None:
        self.stop_opto()
