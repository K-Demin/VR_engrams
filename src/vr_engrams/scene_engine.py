from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from .logger import ExperimentLogger


@dataclass
class SceneEngine:
    """Runs scene A/B blocks and enforces single-modality dropout windows."""

    logger: ExperimentLogger
    phase_name: str
    seed: int | None = None
    dropout_interval_sec: float = 10.0
    dropout_interval_jitter_sec: float = 1.0
    dropout_duration_min_sec: float = 2.0
    dropout_duration_max_sec: float = 4.0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._modalities = ("visual", "sound", "whisker")

    def _scene_modalities(self, scene_label: str) -> dict[str, str]:
        normalized = str(scene_label).strip().upper()
        return {
            "visual": normalized,
            "sound": normalized,
            "whisker": normalized,
        }

    def _next_dropout_delay(self) -> float:
        return self._rng.uniform(
            max(0.1, self.dropout_interval_sec - self.dropout_interval_jitter_sec),
            self.dropout_interval_sec + self.dropout_interval_jitter_sec,
        )

    def _next_dropout_duration(self) -> float:
        return self._rng.uniform(self.dropout_duration_min_sec, self.dropout_duration_max_sec)

    def run_condition(
        self,
        scene_label: str,
        condition_index: int,
        repetition: int,
        duration_sec: float,
    ) -> None:
        scene_modalities = self._scene_modalities(scene_label)
        scene_t0 = time.perf_counter()
        next_dropout_elapsed = self._next_dropout_delay()

        self.logger.log_event(
            "scene_start",
            phase=self.phase_name,
            scene=scene_label,
            condition_index=condition_index,
            repetition=repetition,
            duration_sec=duration_sec,
            active_modalities=scene_modalities,
        )

        while True:
            elapsed = time.perf_counter() - scene_t0
            remaining = duration_sec - elapsed
            if remaining <= 0:
                break

            if elapsed >= next_dropout_elapsed:
                modality = self._rng.choice(self._modalities)
                dropout_duration = min(self._next_dropout_duration(), max(0.0, remaining))

                self.logger.log_event(
                    "modality_dropout_start",
                    phase=self.phase_name,
                    scene=scene_label,
                    condition_index=condition_index,
                    repetition=repetition,
                    modality=modality,
                    modality_variant=scene_modalities[modality],
                    dropout_duration_sec=round(dropout_duration, 3),
                )

                if dropout_duration > 0:
                    time.sleep(dropout_duration)

                self.logger.log_event(
                    "modality_dropout_end",
                    phase=self.phase_name,
                    scene=scene_label,
                    condition_index=condition_index,
                    repetition=repetition,
                    modality=modality,
                    modality_variant=scene_modalities[modality],
                )

                next_dropout_elapsed += self._next_dropout_delay()
            else:
                time.sleep(min(0.05, remaining))

        self.logger.log_event(
            "scene_end",
            phase=self.phase_name,
            scene=scene_label,
            condition_index=condition_index,
            repetition=repetition,
        )
