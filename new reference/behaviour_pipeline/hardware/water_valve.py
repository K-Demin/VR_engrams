# -*- coding: utf-8 -*-
"""
hardware/water_valve.py

Controls a solenoid water valve via NI-DAQ analog output (0V = closed, 5V = open).

Channel: Dev1/ao1  (analog output — NOT digital)

Calibration guide:
  - Run calibrate() with known n_pulses and duration_ms
  - Weigh the collected water (1 mg ≈ 1 µL)
  - µL per pulse = total_mass_mg / n_pulses
  - Adjust duration_ms in config until target µL/pulse is reached
  - Typical targets: training = 6–8 µL, task = 3–5 µL
"""

import nidaqmx
import time


class WaterValve:

    def __init__(self, channel: str = "Dev1/ao1"):
        """
        Parameters
        ----------
        channel : str
            NI-DAQ analog output channel, e.g. "Dev1/ao1"
        """
        self.channel = channel

    def deliver(self, duration_ms: float):
        """
        Open valve for `duration_ms` milliseconds, then close.

        Parameters
        ----------
        duration_ms : float
            Valve open time in milliseconds (e.g. 40 ms ≈ 4–5 µL)
        """
        with nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(self.channel)
            task.write(5.0)                    # open
            time.sleep(duration_ms / 1000.0)   # hold
            task.write(0.0)                    # close

    def calibrate(self, duration_ms: float = 40, n_pulses: int = 100,
                  interval_s: float = 0.75):
        """
        Deliver n_pulses with fixed timing for gravimetric calibration.
        Collect output in a tube, weigh it, divide by n_pulses.
        1 mg ≈ 1 µL at room temperature.

        Parameters
        ----------
        duration_ms : float
            Valve open time per pulse in milliseconds
        n_pulses    : int
            Number of pulses to deliver
        interval_s  : float
            Time between pulse onsets in seconds (must be > duration_ms/1000)
        """
        print(f"Calibration: {n_pulses} pulses × {duration_ms} ms  "
              f"(interval {interval_s}s)")
        print("Place collection tube now. Starting in 3s...")
        time.sleep(3.0)

        start = time.perf_counter()

        with nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(self.channel)
            for i in range(n_pulses):
                print(f"  Pulse {i + 1}/{n_pulses}")
                task.write(5.0)
                time.sleep(duration_ms / 1000.0)
                task.write(0.0)
                time.sleep(interval_s - duration_ms / 1000.0)

        elapsed = time.perf_counter() - start
        print(f"Calibration complete — {elapsed:.1f}s total")
        print("Weigh the collected water:")
        print(f"  µL per pulse = total_mg / {n_pulses}")
        print(f"  Target: 4–8 µL/pulse depending on task stage")


# ------------------------------------------------------------------
# Quick standalone calibration — run directly if needed
# ------------------------------------------------------------------
if __name__ == "__main__":
    valve = WaterValve("Dev1/ao1")
    valve.calibrate(duration_ms=40, n_pulses=100, interval_s=0.75)
