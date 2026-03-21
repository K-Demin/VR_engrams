# -*- coding: utf-8 -*-
"""Puff controller backed by DAQ-layer trigger helpers."""

from hardware.daq_controller import DaqController


from typing import Optional


class PuffController:

    def __init__(self, channel, daq: Optional[DaqController] = None):
        self.channel = channel
        self.daq = daq or DaqController()

    def puff(self, duration):
        self.daq.pulse_digital_one_shot(self.channel, duration)
