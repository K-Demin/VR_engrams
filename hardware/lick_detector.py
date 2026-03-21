# -*- coding: utf-8 -*-
"""
Lick monitor service:
- continuously samples the IR lick sensor
- detects rising edges
- applies refractory/debounce
- logs high-resolution lick timestamps
- can optionally trigger a reward valve pulse
"""

import threading
import time
from collections import deque
from typing import Callable, Optional, Union

import nidaqmx


Numeric = Union[int, float, bool]


class RewardValveController:
    def __init__(self, channel: str):
        self.channel = channel

    def pulse(self, duration_sec: float):
        if duration_sec <= 0:
            return

        with nidaqmx.Task() as task:
            task.do_channels.add_do_chan(self.channel)
            task.write(False)
            time.sleep(0.001)
            task.write(True)
            time.sleep(duration_sec)
            task.write(False)


class LickMonitorService:
    def __init__(
        self,
        sensor_channel: str,
        logger,
        threshold: float = 0.5,
        logic_mode: str = "high_is_lick",
        refractory_sec: float = 0.05,
        sample_interval_sec: float = 0.001,
        valve_channel: Optional[str] = None,
        valve_open_duration_sec: float = 0.04,
        reward_on_lick: bool = False,
        trial_provider: Optional[Callable[[], int]] = None,
        phase_provider: Optional[Callable[[], str]] = None,
    ):
        self.task = nidaqmx.Task()
        self.task.di_channels.add_di_chan(sensor_channel)

        self.logger = logger
        self.threshold = threshold
        self.logic_mode = logic_mode
        self.refractory_sec = refractory_sec
        self.sample_interval_sec = sample_interval_sec
        self.reward_on_lick = reward_on_lick
        self.trial_provider = trial_provider
        self.phase_provider = phase_provider

        self._reward_valve = RewardValveController(valve_channel) if valve_channel else None
        self._valve_open_duration_sec = valve_open_duration_sec

        self._running = False
        self._thread = None
        self._prev_active = False
        self._last_lick_time = float("-inf")
        self._event_queue = deque()
        self._queue_lock = threading.Lock()

    def set_context_providers(
        self,
        trial_provider: Optional[Callable[[], int]] = None,
        phase_provider: Optional[Callable[[], str]] = None,
    ):
        if trial_provider is not None:
            self.trial_provider = trial_provider
        if phase_provider is not None:
            self.phase_provider = phase_provider

    def start(self):
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="LickMonitorService")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self.task.close()

    def check_lick(self) -> bool:
        """
        Returns True once per detected lick edge.
        Consumes one queued lick event if available.
        """
        with self._queue_lock:
            if self._event_queue:
                self._event_queue.popleft()
                return True
        return False

    def _read_sensor_raw(self) -> Numeric:
        return self.task.read()

    def _sensor_active(self, raw_value: Numeric) -> bool:
        # Supports both boolean DI and numeric AI-style values.
        value = float(raw_value)
        if self.logic_mode == "low_is_lick":
            return value <= self.threshold
        return value >= self.threshold

    def _context_trial(self) -> int:
        if self.trial_provider is None:
            return -1
        return int(self.trial_provider())

    def _context_phase(self) -> str:
        if self.phase_provider is None:
            return "unknown"
        return str(self.phase_provider())

    def _run(self):
        while self._running:
            raw = self._read_sensor_raw()
            active = self._sensor_active(raw)
            now_sec = self.logger.now_sec()

            is_rising = active and (not self._prev_active)
            refractory_ok = (now_sec - self._last_lick_time) >= self.refractory_sec

            if is_rising and refractory_ok:
                self._last_lick_time = now_sec

                with self._queue_lock:
                    self._event_queue.append(now_sec)

                self.logger.log({
                    "event": "lick",
                    "trial": self._context_trial(),
                    "phase": self._context_phase(),
                    "timestamp_sec": f"{now_sec:.6f}",
                    "sensor_state": int(active),
                })

                if self.reward_on_lick and self._reward_valve is not None:
                    self._reward_valve.pulse(self._valve_open_duration_sec)

            self._prev_active = active
            time.sleep(self.sample_interval_sec)


# Backward-compatible name used by the pipeline.
LickDetector = LickMonitorService
