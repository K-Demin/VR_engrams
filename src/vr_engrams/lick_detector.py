from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .daq_controller import DaqController
from .logger import ExperimentLogger


@dataclass
class LickDetector:
    """Continuous lick monitoring with optional reward-on-lick mode."""

    daq: DaqController
    logger: ExperimentLogger
    lick_input_name: str
    reward_callback: Callable[[], None] | None = None
    poll_interval_sec: float = 0.005

    _running: bool = field(default=False, init=False)
    _reward_on_lick: bool = field(default=False, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def start(self, reward_on_lick: bool = False) -> None:
        if self._running:
            return
        self._running = True
        self._reward_on_lick = reward_on_lick
        self._thread = threading.Thread(target=self._loop, daemon=True, name="LickMonitor")
        self._thread.start()
        self.logger.log_event("lick_monitor_started", reward_on_lick=reward_on_lick)

    def _loop(self) -> None:
        while self._running:
            if self.daq.read_input(self.lick_input_name):
                self.logger.log_event("lick_detected")
                if self._reward_on_lick and self.reward_callback is not None:
                    self.reward_callback()
                    self.logger.log_event("lick_reward_triggered")
                time.sleep(0.05)
            time.sleep(self.poll_interval_sec)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.logger.log_event("lick_monitor_stopped")
