# -*- coding: utf-8 -*-
"""
hardware/puff_controller.py

Keeps a single NI-DAQ task open for the whole session.
Opening a new Task() on every puff adds ~50-100ms overhead
which breaks timing at rates above 1 Hz.

Usage:
    puff = PuffController("Dev1/port0/line5")
    puff.puff(0.05)   # 50ms puff
    puff.close()      # call at end of session
"""

import nidaqmx
import time


class PuffController:

    def __init__(self, channel: str):
        self.channel  = channel
        self._task    = nidaqmx.Task()
        self._task.do_channels.add_do_chan(channel)
        self._task.write(False)   # ensure line starts LOW

    def puff(self, duration: float):
        """Fire a single puff of the given duration in seconds."""
        self._task.write(True)
        time.sleep(duration)
        self._task.write(False)

    def close(self):
        """Release the NI-DAQ task. Call once at end of session."""
        try:
            self._task.write(False)   # ensure line is LOW before closing
            self._task.close()
        except Exception:
            pass

    def __del__(self):
        self.close()
