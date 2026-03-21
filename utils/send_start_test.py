# -*- coding: utf-8 -*-
"""
Created on Tue Mar 10 14:37:07 2026

@author: NeuRLab
"""

import zmq

context = zmq.Context()
socket = context.socket(zmq.REQ)

socket.connect("tcp://115.145.185.228:5555")

socket.send_string("START")
reply = socket.recv_string()

print("Camera PC reply:", reply)
