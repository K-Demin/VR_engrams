"""Shock controller for TTL-triggered stimulation.

Designed for runtime use with explicit arm/disarm semantics:
- output line is forced LOW on init and disarm
- trigger is only allowed when armed
- optional event logging hooks for experiment logs
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import nidaqmx


EventHook = Callable[[str, dict], None]


class ShockController:
    """Discrete TTL pulse controller for shock delivery."""

    def __init__(self, line: str, event_hook: Optional[EventHook] = None):
        self.line = line
        self._event_hook = event_hook
        self._task = nidaqmx.Task()
        self._task.do_channels.add_do_chan(self.line)
        self._armed = False
        self._set_low()
        self._log("shock_init", line=self.line, armed=self._armed)

    @property
    def armed(self) -> bool:
        return self._armed

    def arm(self) -> None:
        self._set_low()
        self._armed = True
        self._log("shock_armed", line=self.line)

    def disarm(self) -> None:
        self._set_low()
        self._armed = False
        self._log("shock_disarmed", line=self.line)

    def trigger(self, pulse_ms: float = 50.0) -> None:
        if not self._armed:
            raise RuntimeError("ShockController trigger requested while disarmed")

        self._log("shock_trigger_start", pulse_ms=pulse_ms)
        self._task.write(True)
        time.sleep(pulse_ms / 1000.0)
        self._set_low()
        self._log("shock_trigger_end", pulse_ms=pulse_ms)

    def close(self) -> None:
        self.disarm()
        self._task.close()
        self._log("shock_closed", line=self.line)

    def _set_low(self) -> None:
        self._task.write(False)

    def _log(self, event: str, **fields) -> None:
        if self._event_hook is not None:
            self._event_hook(event, fields)

