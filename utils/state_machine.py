# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:42:29 2026

@author: JoshB
"""

import time


class StateMachine:

    def __init__(self):

        self.state = None
        self.state_start = None

    def set_state(self, new_state):

        self.state = new_state
        self.state_start = time.time()

        print(f"STATE -> {new_state}")

    def time_in_state(self):

        return time.time() - self.state_start