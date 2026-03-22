from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class VisualEngine:
    """Minimal PsychoPy-backed visual presenter with graceful fallback."""

    enabled: bool = False
    screen_index: int = 1
    fullscreen: bool = True
    width: int = 1920
    height: int = 1080

    def __post_init__(self) -> None:
        self._visual = None
        self._core = None
        self._window = None
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
            self._window = visual.Window(
                size=[self.width, self.height],
                fullscr=self.fullscreen,
                units="pix",
                screen=self.screen_index,
                allowGUI=False,
                color=[-1, -1, -1],
            )
        except Exception as exc:
            self.enabled = False
            self.init_error = f"psychopy_window_failed: {exc}"
            return

    def present(self, stimulus: str, duration_sec: float) -> bool:
        if not self.enabled or self._visual is None or self._window is None:
            return False

        if stimulus == "screen_a":
            patch = self._visual.GratingStim(self._window, tex="sin", mask=None, sf=0.01, ori=0, contrast=0.5)
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < duration_sec:
                patch.phase += 0.03
                patch.draw()
                self._window.flip()
            return True

        if stimulus == "screen_b":
            dots = self._visual.DotStim(
                self._window,
                fieldSize=self._window.size[0],
                nDots=200,
                dotSize=5,
                speed=2.0,
                coherence=0.0,
                fieldShape="rectangle",
                units="pix",
            )
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < duration_sec:
                dots.draw()
                self._window.flip()
            return True

        return False

    def close(self) -> None:
        if self._window is not None:
            self._window.close()
            self._window = None
