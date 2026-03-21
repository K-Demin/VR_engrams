# -*- coding: utf-8 -*-
"""Fear conditioning phase: continuous target scene with spaced shock triggers."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ShockEvent:
    index: int
    onset_s: float


class FearConditioningPhase:
    """Continuous scene presentation with constrained shock spacing."""

    def __init__(self, config: Dict, logger=None):
        self.config = config
        self.logger = logger

        session_cfg = config["session"]
        shock_cfg = config["shock"]
        random_cfg = config.get("randomization", {})

        self.target_scene = session_cfg["target_scene"]
        self.total_duration_s = session_cfg["total_duration_s"]

        self.shock_count_min = shock_cfg["count_min"]
        self.shock_count_max = shock_cfg["count_max"]
        self.shock_spacing_min_s = shock_cfg["spacing_min_s"]
        self.shock_spacing_max_s = shock_cfg["spacing_max_s"]

        self.seed = random_cfg.get("seed")
        self._rng = random.Random(self.seed)

    def _sample_valid_shocks(self) -> List[ShockEvent]:
        shock_count = self._rng.randint(self.shock_count_min, self.shock_count_max)

        for _ in range(self.config["shock"]["max_sampling_attempts"]):
            shocks: List[ShockEvent] = []
            t = self._rng.uniform(0.0, self.shock_spacing_max_s)

            for idx in range(shock_count):
                if idx == 0:
                    onset = t
                else:
                    onset = shocks[-1].onset_s + self._rng.uniform(
                        self.shock_spacing_min_s, self.shock_spacing_max_s
                    )
                shocks.append(ShockEvent(index=idx, onset_s=onset))

            if shocks[-1].onset_s <= self.total_duration_s:
                return shocks

        raise ValueError(
            "Unable to sample shock schedule with configured total duration and spacing constraints"
        )

    def build_shock_schedule(self) -> List[ShockEvent]:
        return self._sample_valid_shocks()

    def run(self, sleep: bool = True) -> List[ShockEvent]:
        shock_schedule = self.build_shock_schedule()
        t0 = time.time()

        if self.logger:
            self.logger.log(
                {
                    "event": "target_scene_start",
                    "scene": self.target_scene,
                    "total_duration_s": self.total_duration_s,
                }
            )

        next_shock_idx = 0
        while True:
            elapsed = time.time() - t0
            if elapsed >= self.total_duration_s:
                break

            if next_shock_idx < len(shock_schedule) and elapsed >= shock_schedule[next_shock_idx].onset_s:
                if self.logger:
                    self.logger.log(
                        {
                            "event": "shock_trigger",
                            "shock_index": shock_schedule[next_shock_idx].index,
                            "onset_s": round(elapsed, 3),
                        }
                    )
                next_shock_idx += 1

            if sleep:
                time.sleep(0.01)
            else:
                break

        if self.logger:
            self.logger.log({"event": "target_scene_end", "scene": self.target_scene})

        return shock_schedule
