from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class AudioEngine:
    """Non-blocking stereo tone backend with graceful fallback if dependencies are missing."""

    samplerate: int = 48_000
    device: int | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._sd = None
        self._np = None
        if not self.enabled:
            return
        try:
            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore
        except Exception:
            self.enabled = False
            return
        self._np = np
        self._sd = sd

    def play_tone(self, frequency_hz: float, duration_sec: float, side: str = "both", volume: float = 0.25) -> bool:
        if not self.enabled or self._sd is None or self._np is None:
            return False

        self.stop()

        def _play() -> None:
            n_samples = max(1, int(self.samplerate * duration_sec))
            t = self._np.linspace(0, duration_sec, n_samples, endpoint=False)
            mono = (volume * self._np.sin(2 * self._np.pi * frequency_hz * t)).astype("float32")
            stereo = self._np.zeros((len(mono), 2), dtype="float32")
            if side == "left":
                stereo[:, 0] = mono
            elif side == "right":
                stereo[:, 1] = mono
            else:
                stereo[:, 0] = mono
                stereo[:, 1] = mono

            self._sd.play(stereo, self.samplerate, device=self.device)
            self._sd.wait()

        self._thread = threading.Thread(target=_play, daemon=True, name="VREngramsAudioTone")
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._sd is not None:
            self._sd.stop()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
            self._thread = None
