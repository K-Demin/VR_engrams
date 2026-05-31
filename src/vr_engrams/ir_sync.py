from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .daq_controller import DaqController
from .logger import ExperimentLogger


@dataclass
class IRSyncController:
    """Emit short IR LED pulses that appear in the camera stream."""

    daq: DaqController
    logger: ExperimentLogger
    output_name: str = "ir_led"
    pulse_duration_sec: float = 0.5

    def pulse(self, label: str, blocking: bool = True) -> None:
        if blocking:
            self._pulse(label)
            return

        thread = threading.Thread(target=self._pulse, args=(label,), daemon=True, name=f"IRSync-{label}")
        thread.start()

    def _pulse(self, label: str) -> None:
        wall_time_unix = time.time()
        path = self.daq.pulse_output(self.output_name, self.pulse_duration_sec)
        self.logger.log_event(
            label,
            output_name=self.output_name,
            duration_sec=self.pulse_duration_sec,
            wall_time_unix=wall_time_unix,
            pulse_path=path,
        )

    @classmethod
    def from_config(cls, daq: DaqController, logger: ExperimentLogger, config: dict[str, Any]) -> "IRSyncController | None":
        imaging = config.get("imaging", {}) if isinstance(config.get("imaging", {}), dict) else {}
        output_name = str(imaging.get("ir_led_output_name", "ir_led"))
        channels = config.get("channels", {}) if isinstance(config.get("channels", {}), dict) else {}
        if output_name not in channels.get("digital_outputs", {}):
            return None
        return cls(
            daq=daq,
            logger=logger,
            output_name=output_name,
            pulse_duration_sec=float(imaging.get("ir_led_pulse_duration_sec", 0.5)),
        )
