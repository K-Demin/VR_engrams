# -*- coding: utf-8 -*-
"""
Created on Mon Apr 20 16:39:15 2026

@author: NeuRLab
"""

# hardware/ir_led_controller.py

import nidaqmx
import time
import logging

logger = logging.getLogger(__name__)

class IRLEDController:
    """
    Controls IR LED via NI-DAQ digital output.
    Used to generate sync pulses visible in body/face camera.
    """

    def __init__(self, channel: str):
        """
        Parameters
        ----------
        channel : str
            NI-DAQ digital output line, e.g. "Dev1/port0/line1"
            NOTE: Do not share this line with lick detector input.
            Use a separate line.
        """
        self.channel = channel
        self._task = None
        self._setup()

    def _setup(self):
        self._task = nidaqmx.Task()
        self._task.do_channels.add_do_chan(self.channel)
        self._task.write(False)  # ensure LED starts OFF

    def pulse(self, duration: float = 0.5) -> float:
        """
        Fire a single synchronisation pulse.
        Blocks for duration seconds, then turns LED off.
        Returns the time.time() at LED ON — use this as your sync timestamp.

        Parameters
        ----------
        duration : float
            Pulse duration in seconds. 0.5s is long enough to
            guarantee capture in at least one 30Hz frame (~33ms/frame).
        """
        t_on = time.time()
        self._task.write(True)
        time.sleep(duration)
        self._task.write(False)
        logger.info(f"IR LED sync pulse fired at t={t_on:.4f}, duration={duration:.3f}s")
        return t_on

    def close(self):
        if self._task is not None:
            self._task.write(False)
            self._task.close()
            self._task = None

    def __del__(self):
        self.close()