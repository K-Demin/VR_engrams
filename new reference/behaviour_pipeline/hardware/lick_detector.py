# -*- coding: utf-8 -*-
"""
hardware/lick_detector.py

Lick detector supporting both digital (TTL) and analog (capacitive/piezo) inputs.

Digital mode  — reads a DI channel directly (True/False)
Analog mode   — reads AI voltage; lick = value < threshold
"""

import nidaqmx
from nidaqmx.constants import TerminalConfiguration


class LickDetector:

    def __init__(self, channel: str, mode: str = "digital", threshold: float = 1.0):
        """
        Parameters
        ----------
        channel   : NI-DAQ channel string
                    Digital: "Dev1/port0/line1"
                    Analog:  "Dev1/ai2"
        mode      : "digital" or "analog"
        threshold : Voltage below which a lick is detected (analog mode only)
        """
        self.mode      = mode
        self.threshold = threshold

        self.task = nidaqmx.Task()

        if mode == "analog":
            self.task.ai_channels.add_ai_voltage_chan(
                channel,
                terminal_config=TerminalConfiguration.RSE
            )
        else:
            self.task.di_channels.add_di_chan(channel)

    def check_lick(self) -> bool:
        """Return True if a lick is currently detected."""
        value = self.task.read()
        if self.mode == "analog":
            return value < self.threshold
        return bool(value)

    def close(self):
        self.task.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
