from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from .context import PhaseContext


class ExperimentPhase(ABC):
    """Base class for all experiment phase wrappers."""

    phase_key: str
    display_name: str

    def __init__(self, context: PhaseContext, config: dict[str, Any]):
        self.context = context
        self.config = config

    @abstractmethod
    def run(self) -> None:
        """Execute this phase using runtime context and phase config."""

    def _require(self, key: str) -> Any:
        if key not in self.config:
            raise ValueError(f"Missing required config key '{key}' for phase '{self.phase_key}'")
        return self.config[key]

    def _sleep(self, duration_sec: float) -> None:
        if duration_sec < 0:
            raise ValueError(f"Negative duration not allowed in phase '{self.phase_key}': {duration_sec}")
        time.sleep(duration_sec)
