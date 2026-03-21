# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:33:58 2026

@author: JoshB
"""

import nidaqmx

class LickDetector:

    def __init__(self, channel):

        self.task = nidaqmx.Task()
        self.task.di_channels.add_di_chan(channel)

    def check_lick(self):

        value = self.task.read()

        return value