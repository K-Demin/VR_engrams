# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:33:29 2026

@author: JoshB
"""

import nidaqmx
import time

class PuffController:

    def __init__(self, channel):

        self.channel = channel

    def puff(self, duration):

        with nidaqmx.Task() as task:

            task.do_channels.add_do_chan(self.channel)

            task.write(False)
            time.sleep(0.005)

            task.write(True)
            time.sleep(duration)

            task.write(False)