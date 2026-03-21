# -*- coding: utf-8 -*-
"""fMRI opto phase with configurable ON/OFF loop timing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class OptoCycle:
    index: int
    on_duration_s: float
    off_duration_s: float


class FMRIOptoPhase:
    """Alternates opto ON/OFF until total duration is reached."""

    def __init__(self, config: Dict, logger=None):
        self.config = config
        self.logger = logger

        timing_cfg = config["timing"]
        self.on_duration_s = timing_cfg["on_duration_s"]
        self.off_duration_s = timing_cfg["off_duration_s"]
        self.total_duration_s = timing_cfg["total_duration_s"]

    def build_cycle_plan(self) -> List[OptoCycle]:
        cycles: List[OptoCycle] = []
        elapsed = 0.0
        idx = 0

        while elapsed < self.total_duration_s:
            remaining = self.total_duration_s - elapsed
            on_dur = min(self.on_duration_s, max(remaining, 0.0))
            remaining -= on_dur
            off_dur = min(self.off_duration_s, max(remaining, 0.0))

            cycles.append(OptoCycle(index=idx, on_duration_s=on_dur, off_duration_s=off_dur))
            elapsed += on_dur + off_dur
            idx += 1

        return cycles

    def run(self, sleep: bool = True) -> List[OptoCycle]:
        cycles = self.build_cycle_plan()

        for cycle in cycles:
            if self.logger:
                self.logger.log(
                    {
                        "event": "opto_on",
                        "cycle": cycle.index,
                        "duration_s": round(cycle.on_duration_s, 3),
                    }
                )
            if sleep and cycle.on_duration_s > 0:
                time.sleep(cycle.on_duration_s)

            if self.logger:
                self.logger.log(
                    {
                        "event": "opto_off",
                        "cycle": cycle.index,
                        "duration_s": round(cycle.off_duration_s, 3),
                    }
                )
            if sleep and cycle.off_duration_s > 0:
                time.sleep(cycle.off_duration_s)

        return cycles
