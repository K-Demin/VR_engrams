from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from vr_engrams_v2.interfaces import IDaqController, IExperimentLogger, ILickMonitor


@dataclass
class ImprovedLickMonitor(ILickMonitor):
    """Edge-detected lick monitor with debounce and optional reward callback."""

    daq: IDaqController
    logger: IExperimentLogger
    lick_input_name: str
    reward_callback: Callable[[], None] | None = None
    poll_interval_sec: float = 0.002
    debounce_sec: float = 0.03

    _running: bool = field(default=False, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _reward_on_lick: bool = field(default=False, init=False)
    _last_lick_ts: float = field(default=0.0, init=False)
    _last_state: bool = field(default=False, init=False)

    def start(self, reward_on_lick: bool = False) -> None:
        if self._running:
            return
        self._running = True
        self._reward_on_lick = reward_on_lick
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ImprovedLickMonitor")
        self._thread.start()
        self.logger.log_event("lick_monitor_started", reward_on_lick=reward_on_lick, monitor="improved")

    def _loop(self) -> None:
        while self._running:
            current_state = self.daq.read_input(self.lick_input_name)
            now = time.perf_counter()
            rising_edge = current_state and not self._last_state
            not_debounced = (now - self._last_lick_ts) >= self.debounce_sec

            if rising_edge and not_debounced:
                self._last_lick_ts = now
                self.logger.log_event("lick_detected", monitor="improved")
                if self._reward_on_lick and self.reward_callback is not None:
                    self.reward_callback()
                    self.logger.log_event("lick_reward_triggered", monitor="improved")

            self._last_state = current_state
            time.sleep(self.poll_interval_sec)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.logger.log_event("lick_monitor_stopped", monitor="improved")
