# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:55:42 2026

@author: JoshB
"""

import os
import time
from master9_controller import Master9Controller

SIGNAL_DIR = r"Y:\signals"

master9 = Master9Controller(port="COM3")

print("Master-9 listener running")

while True:

    master9.stop_all()
    start_file = os.path.join(SIGNAL_DIR, "START_SESSION")
    stop_file = os.path.join(SIGNAL_DIR, "STOP_SESSION")

    if os.path.exists(start_file):

        print("Starting Master-9 program")

        master9.trigger_channel(1)

        os.remove(start_file)

    if os.path.exists(stop_file):

        print("Stopping Master-9")

        master9.stop_all()

        os.remove(stop_file)

    time.sleep(0.1)