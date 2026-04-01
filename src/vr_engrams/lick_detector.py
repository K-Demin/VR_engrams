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
    threshold: float = 2.5
    logic_mode: str = "high_is_lick"
    refractory_sec: float = 0.05

    _running: bool = field(default=False, init=False)
    _reward_on_lick: bool = field(default=False, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _prev_active: bool = field(default=False, init=False)
    _last_lick_time: float = field(default=float("-inf"), init=False)

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
            raw_value = self.daq.read_input(self.lick_input_name)
            active = self._sensor_active(raw_value)
            self.logger.log_lick_sample(raw_value=raw_value, active=active)

            now = time.perf_counter()
            is_rising = active and (not self._prev_active)
            refractory_ok = (now - self._last_lick_time) >= self.refractory_sec
            if is_rising and refractory_ok:
                self._last_lick_time = now
                self.logger.log_event("lick_detected", sensor_value=raw_value)
                if self._reward_on_lick and self.reward_callback is not None:
                    self.reward_callback()
                    self.logger.log_event("lick_reward_triggered")
            self._prev_active = active
            time.sleep(self.poll_interval_sec)

    def _sensor_active(self, raw_value: float | bool) -> bool:
        if isinstance(raw_value, bool):
            return raw_value if self.logic_mode == "high_is_lick" else (not raw_value)

        value = float(raw_value)
        if self.logic_mode == "low_is_lick":
            return value <= self.threshold
        return value >= self.threshold

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.logger.log_event("lick_monitor_stopped")
