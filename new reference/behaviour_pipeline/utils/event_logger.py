# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:43:00 2026

@author: JoshB
"""

import csv
import time


class EventLogger:

    def __init__(self, filename):

        self.file = open(filename, "w", newline="")
        self.writer = csv.writer(self.file)

        self.writer.writerow(["time", "event"])

        self.start_time = time.time()

    def log(self, event):

        t = time.time() - self.start_time

        self.writer.writerow([t, event])
        self.file.flush()

        print(f"{t:.3f} {event}")