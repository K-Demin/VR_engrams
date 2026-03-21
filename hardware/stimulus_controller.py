"""High-level stimulus orchestration with phase/mode constraints.

Constraints:
- Shock is only callable in the conditioning phase.
- Opto supports:
  * scene mode (behavioural)
  * block mode (fMRI)
"""

from __future__ import annotations

from typing import Callable, Optional

from hardware.opto_controller import OptoController
from hardware.shock_controller import ShockController


EventHook = Callable[[str, dict], None]


class StimulusController:
    """Coordinate shock and opto controllers with explicit runtime constraints."""

    VALID_PHASES = {"habituation", "conditioning", "extinction"}
    VALID_OPTO_MODES = {"scene", "block"}

    def __init__(
        self,
        shock_controller: ShockController,
        opto_controller: OptoController,
        *,
        event_hook: Optional[EventHook] = None,
    ):
        self.shock = shock_controller
        self.opto = opto_controller
        self.phase = "habituation"
        self._event_hook = event_hook
        self._log("stimulus_init", phase=self.phase)

    def set_phase(self, phase: str) -> None:
        if phase not in self.VALID_PHASES:
            raise ValueError(f"Unknown phase: {phase}")
        self.phase = phase
        self._log("stimulus_phase_set", phase=self.phase)

    def deliver_shock(self, pulse_ms: float = 50.0) -> None:
        if self.phase != "conditioning":
            raise RuntimeError(
                f"Shock delivery is only allowed in conditioning phase, current: {self.phase}"
            )
        self._log("stimulus_shock_request", pulse_ms=pulse_ms)
        self.shock.trigger(pulse_ms=pulse_ms)

    def run_opto_scene_mode(self) -> None:
        """Behavioural scene mode: start train for scene-coupled epochs."""
        self._run_opto_mode("scene")

    def run_opto_block_mode(self) -> None:
        """fMRI block mode: start train for longer block epochs."""
        self._run_opto_mode("block")

    def stop_opto(self) -> None:
        self.opto.stop()
        self._log("stimulus_opto_stop")

    def close(self) -> None:
        self.opto.close()
        self.shock.close()
        self._log("stimulus_closed")

    def _run_opto_mode(self, mode: str) -> None:
        if mode not in self.VALID_OPTO_MODES:
            raise ValueError(f"Unknown opto mode: {mode}")
        self._log("stimulus_opto_start", mode=mode)
        self.opto.start()

    def _log(self, event: str, **fields) -> None:
        if self._event_hook is not None:
            self._event_hook(event, fields)

