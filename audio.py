# -*- coding: utf-8 -*-
"""
Created on Mon Feb 16 17:17:55 2026

@author: NeuRLab
"""

import sounddevice as sd

AUDIO_DEVICE = 4        # WASAPI device
SAMPLERATE = 48000      # confirmed working

sd.default.device = AUDIO_DEVICE
sd.default.latency = 'low'

import numpy as np

def play_tone(freq=1000, duration_ms=200, volume=0.5):
    duration = duration_ms / 1000
    t = np.linspace(0, duration, int(SAMPLERATE * duration), False)
    tone = volume * np.sin(2 * np.pi * freq * t)
    sd.play(tone, SAMPLERATE)
