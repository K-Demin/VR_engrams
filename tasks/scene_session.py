# -*- coding: utf-8 -*-
"""Scene session phase with asynchronous single-modality dropout."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ConditionEvent:
    index: int
    condition: str
    duration_s: float


@dataclass(frozen=True)
class DropoutEvent:
    onset_s: float
    offset_s: float
    modality: str


class SceneSessionPhase:
    """Runs target/non-target/empty/opto conditions plus async modality dropout."""

    def __init__(self, config: Dict, logger=None):
        self.config = config
        self.logger = logger

        session_cfg = config["session"]
        dropout_cfg = config["dropout"]

        self.condition_order = list(session_cfg["condition_order"])
        self.condition_repetitions = session_cfg["condition_repetitions"]
        self.condition_duration_s = dict(session_cfg["condition_duration_s"])

        self.dropout_enabled = dropout_cfg["enabled"]
        self.dropout_interval_min_s = dropout_cfg["interval_min_s"]
        self.dropout_interval_max_s = dropout_cfg["interval_max_s"]
        self.dropout_duration_min_s = dropout_cfg["duration_min_s"]
        self.dropout_duration_max_s = dropout_cfg["duration_max_s"]
        self.modalities = list(dropout_cfg["modalities"])

        self.seed = config.get("randomization", {}).get("seed")
        self._rng = random.Random(self.seed)

    def build_condition_schedule(self) -> List[ConditionEvent]:
        sequence: List[ConditionEvent] = []
        idx = 0

        for _ in range(self.condition_repetitions):
            for condition in self.condition_order:
                sequence.append(
                    ConditionEvent(
                        index=idx,
                        condition=condition,
                        duration_s=self.condition_duration_s[condition],
                    )
                )
                idx += 1

        return sequence

    def _next_dropout_delay(self) -> float:
        return self._rng.uniform(self.dropout_interval_min_s, self.dropout_interval_max_s)

    def _next_dropout_duration(self) -> float:
        return self._rng.uniform(self.dropout_duration_min_s, self.dropout_duration_max_s)

    def run(self, sleep: bool = True) -> Dict[str, List]:
        condition_schedule = self.build_condition_schedule()
        dropout_events: List[DropoutEvent] = []

        experiment_t0 = time.time()
        next_dropout_t = self._next_dropout_delay()

        for block in condition_schedule:
            block_start_t = time.time()

            if self.logger:
                self.logger.log(
                    {
                        "event": "condition_start",
                        "condition_idx": block.index,
                        "condition": block.condition,
                        "duration_s": block.duration_s,
                    }
                )

            while True:
                elapsed_total = time.time() - experiment_t0
                elapsed_block = time.time() - block_start_t
                remaining_in_block = block.duration_s - elapsed_block

                if remaining_in_block <= 0:
                    break

                if self.dropout_enabled and elapsed_total >= next_dropout_t:
                    modality = self._rng.choice(self.modalities)
                    dropout_len = min(self._next_dropout_duration(), max(remaining_in_block, 0.0))
                    onset = time.time() - experiment_t0

                    if self.logger:
                        self.logger.log(
                            {
                                "event": "dropout_start",
                                "modality": modality,
                                "condition": block.condition,
                                "duration_s": round(dropout_len, 3),
                            }
                        )

                    if sleep and dropout_len > 0:
                        time.sleep(dropout_len)

                    offset = time.time() - experiment_t0
                    dropout_events.append(
                        DropoutEvent(onset_s=onset, offset_s=offset, modality=modality)
                    )

                    if self.logger:
                        self.logger.log(
                            {
                                "event": "dropout_end",
                                "modality": modality,
                                "condition": block.condition,
                            }
                        )

                    next_dropout_t += self._next_dropout_delay()
                else:
                    sleep_step = min(remaining_in_block, 0.05)
                    if sleep and sleep_step > 0:
                        time.sleep(sleep_step)
                    else:
                        break

            if self.logger:
                self.logger.log(
                    {
                        "event": "condition_end",
                        "condition_idx": block.index,
                        "condition": block.condition,
                    }
                )

        return {"conditions": condition_schedule, "dropouts": dropout_events}
