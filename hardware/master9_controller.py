# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:54:56 2026

@author: JoshB
"""

import serial
import time


class Master9Controller:

    def __init__(self, port="COM3", baudrate=9600):
        self.ser = serial.Serial(port, baudrate, timeout=1)
        time.sleep(2)

    def send(self, command):
        cmd = command + "\r"
        self.ser.write(cmd.encode())

    def trigger_channel(self, channel):
        self.send(f"TRIG {channel}")

    def stop_all(self):
        self.send("STOP")

    def close(self):
        self.ser.close()