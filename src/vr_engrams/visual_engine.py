from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable


@dataclass
class VisualEngine:
    """Minimal PsychoPy-backed visual presenter with graceful fallback."""

    enabled: bool = False
    screen_index: int = 1
    screen_indices: list[int] | None = None
    fullscreen: bool = True
    width: int = 1920
    height: int = 1080

    def __post_init__(self) -> None:
        self._visual = None
        self._core = None
        self._window = None
        self._windows: list[object] = []
        self.init_error: str | None = None
        if not self.enabled:
            self.init_error = "disabled_by_config"
            return
        try:
            from psychopy import core, visual  # type: ignore
        except Exception as exc:
            self.enabled = False
            self.init_error = f"psychopy_import_failed: {exc}"
            return
        self._visual = visual
        self._core = core
        try:
            target_screens: Iterable[int] = self.screen_indices if self.screen_indices else [self.screen_index]
            for idx in target_screens:
                window_kwargs = {
                    "fullscr": self.fullscreen,
                    "units": "pix",
                    "screen": int(idx),
                    "allowGUI": False,
                    "color": [-1, -1, -1],
                    # Avoid expensive / occasionally-stalling refresh-rate measurements during startup.
                    "checkTiming": False,
                    # Prevent blocking indefinitely on buffer swap on some multi-monitor Windows setups.
                    "waitBlanking": False,
                }
                if not self.fullscreen:
                    window_kwargs["size"] = [self.width, self.height]
                window = visual.Window(
                    **window_kwargs,
                )
                self._windows.append(window)
            self._window = self._windows[0]
            # Windows are already configured with a black background; avoid initial flip here because
            # swapBuffers/dispatch_events can block on some systems before the run loop starts.
            for window in self._windows:
                window.color = [-1, -1, -1]
        except Exception as exc:
            self.enabled = False
            self.init_error = f"psychopy_window_failed: {exc}"
            return

    def show_black(self) -> None:
        if not self.enabled or not self._windows:
            return
        for window in self._windows:
            window.color = [-1, -1, -1]
            window.flip()

    def present(self, stimulus: str, duration_sec: float) -> bool:
        if not self.enabled or self._visual is None or not self._windows:
            return False

        if stimulus == "screen_a":
            patches = [
                self._visual.GratingStim(
                    w,
                    tex="sin",
                    mask=None,
                    sf=0.01,
                    ori=0,
                    contrast=0.5,
                    size=w.size,
                    units="pix",
                )
                for w in self._windows
            ]
            t0 = time.perf_counter()
            try:
                while time.perf_counter() - t0 < duration_sec:
                    for patch in patches:
                        patch.phase += 0.03
                        patch.draw()
                    for window in self._windows:
                        window.flip()
            finally:
                self.show_black()
            return True

        if stimulus == "screen_b":
            dots_stimuli = [
                self._visual.DotStim(
                    window,
                    fieldSize=window.size,
                    nDots=200,
                    dotSize=7,
                    speed=2.0,
                    coherence=0.0,
                    fieldShape="rectangle",
                    units="pix",
                )
                for window in self._windows
            ]
            t0 = time.perf_counter()
            try:
                while time.perf_counter() - t0 < duration_sec:
                    for dots in dots_stimuli:
                        dots.draw()
                    for window in self._windows:
                        window.flip()
            finally:
                self.show_black()
            return True

        return False

    def close(self) -> None:
        for window in self._windows:
            window.close()
        self._windows = []
        self._window = None
