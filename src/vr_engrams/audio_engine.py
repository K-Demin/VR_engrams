from __future__ import annotations

import threading
from dataclasses import dataclass
import time


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
        self._winsound = None
        self.init_error: str | None = None
        self.active_backend: str | None = None
        if not self.enabled:
            self.init_error = "disabled_by_config"
            return
        try:
            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore
            self._np = np
            self._sd = sd
            self.active_backend = "sounddevice"
            return
        except Exception as sounddevice_exc:
            self.init_error = f"sounddevice_unavailable: {sounddevice_exc}"

        # Windows fallback: ensure at least a basic audible tone path exists.
        try:
            import winsound  # type: ignore

            self._winsound = winsound
            self.active_backend = "winsound"
        except Exception as winsound_exc:
            self.enabled = False
            self.init_error = f"{self.init_error}; winsound_unavailable: {winsound_exc}"

    def play_tone(self, frequency_hz: float, duration_sec: float, side: str = "both", volume: float = 0.25) -> str | None:
        if not self.enabled:
            return None

        self.stop()

        if self.active_backend == "sounddevice" and self._sd is not None and self._np is not None:
            def _play_sounddevice() -> None:
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

            self._thread = threading.Thread(target=_play_sounddevice, daemon=True, name="VREngramsAudioTone")
            self._thread.start()
            return "sounddevice"

        if self.active_backend == "winsound" and self._winsound is not None:
            def _play_winsound() -> None:
                freq = int(max(37.0, min(32767.0, float(frequency_hz))))
                duration_ms = int(max(1, round(float(duration_sec) * 1000.0)))
                # winsound is mono/beep-only, so side/volume are not used.
                self._winsound.Beep(freq, duration_ms)

            self._thread = threading.Thread(target=_play_winsound, daemon=True, name="VREngramsAudioToneWin")
            self._thread.start()
            return "winsound"

        # Defensive fallback if backend probes failed after init.
        time.sleep(duration_sec)
        return "sleep_fallback"

    def stop(self) -> None:
        if self._sd is not None:
            self._sd.stop()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
            self._thread = None
