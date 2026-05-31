# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:34:20 2026

@author: JoshB
"""

# hardware/audio_controller.py
#
# Non-blocking stereo audio controller for puff task.
# play_tone() returns immediately — audio plays in background thread.
# This prevents sd.wait() from blocking the FSM loop.
#
# Mice hear best between ~8-32kHz.
# Recommended: 8kHz (left), 16kHz (right)

import numpy as np
import sounddevice as sd
import threading


class AudioController:

    def __init__(self, samplerate: int = 48000, device: int = None):
        """
        Parameters
        ----------
        samplerate : int
            48000 recommended for WASAPI on Windows (44100 may fail).
        device : int or None
            Sounddevice output device index. None = system default.
            Run AudioController.list_devices() to find correct index.
        """
        self.samplerate = samplerate
        self.device     = device
        self._thread    = None

    @staticmethod
    def list_devices():
        """Print all available audio devices."""
        print(sd.query_devices())

    def play_tone(self, freq: float, duration: float,
                  side: str = "both", volume: float = 0.25):
        """
        Play a pure tone to the specified speaker — NON-BLOCKING.
        Returns immediately. Audio plays in a background thread.
        FSM loop continues at full speed while tone plays.

        Parameters
        ----------
        freq     : Frequency in Hz (e.g. 8000 for 8kHz)
        duration : Duration in seconds
        side     : "left", "right", or "both"
        volume   : Amplitude 0.0-1.0 (default 0.25)
        """
        # Stop any currently playing tone before starting new one
        self.stop()

        def _play():
            t      = np.linspace(0, duration,
                                 int(self.samplerate * duration),
                                 endpoint=False)
            mono   = (volume * np.sin(2 * np.pi * freq * t)).astype(np.float32)
            stereo = np.zeros((len(mono), 2), dtype=np.float32)

            if side == "left":
                stereo[:, 0] = mono
            elif side == "right":
                stereo[:, 1] = mono
            else:
                stereo[:, 0] = mono
                stereo[:, 1] = mono

            sd.play(stereo, self.samplerate, device=self.device)
            sd.wait()   # blocks inside thread only — main FSM unaffected

        self._thread = threading.Thread(target=_play, daemon=True, name="AudioTone")
        self._thread.start()

    def stop(self):
        """Stop any currently playing audio immediately."""
        sd.stop()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
            self._thread = None