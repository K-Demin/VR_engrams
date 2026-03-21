from __future__ import annotations

import importlib
import importlib.util
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DaqController:
    """NI-DAQ digital output/input helper with reusable tasks."""

    enabled: bool = True
    do_tasks: dict[str, Any] = field(default_factory=dict)
    di_tasks: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._nidaqmx = None
        if importlib.util.find_spec("nidaqmx") is None:
            self.enabled = False
            return
        self._nidaqmx = importlib.import_module("nidaqmx")

    def create_digital_output(self, name: str, channel: str) -> None:
        if not self.enabled:
            return
        task = self._nidaqmx.Task(new_task_name=f"do_{name}")
        task.do_channels.add_do_chan(channel)
        self.do_tasks[name] = task

    def create_digital_input(self, name: str, channel: str) -> None:
        if not self.enabled:
            return
        task = self._nidaqmx.Task(new_task_name=f"di_{name}")
        task.di_channels.add_di_chan(channel)
        self.di_tasks[name] = task

    def pulse_output(self, name: str, duration_sec: float) -> None:
        if not self.enabled:
            time.sleep(duration_sec)
            return
        task = self.do_tasks[name]
        task.write(True)
        time.sleep(duration_sec)
        task.write(False)

    def write_output(self, name: str, state: bool) -> None:
        if self.enabled:
            self.do_tasks[name].write(state)

    def read_input(self, name: str) -> bool:
        if not self.enabled:
            return False
        return bool(self.di_tasks[name].read())

    def close(self) -> None:
        for task in list(self.do_tasks.values()) + list(self.di_tasks.values()):
            task.close()
        self.do_tasks.clear()
        self.di_tasks.clear()
