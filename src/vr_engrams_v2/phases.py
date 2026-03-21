from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from vr_engrams_v2.interfaces import IExperimentLogger, IPhase


@dataclass
class CallablePhase(IPhase):
    """Simple phase wrapper for migration-friendly composition."""

    phase_name: str
    runner: Callable[[], None]
    logger: IExperimentLogger

    @property
    def name(self) -> str:
        return self.phase_name

    def run(self) -> None:
        self.logger.log_event("phase_start", phase=self.phase_name)
        self.runner()
        self.logger.log_event("phase_end", phase=self.phase_name)
