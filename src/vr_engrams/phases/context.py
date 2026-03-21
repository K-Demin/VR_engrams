from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from ..lick_detector import LickDetector
from ..logger import ExperimentLogger
from ..stimulus_controller import StimulusController


@dataclass(frozen=True)
class PhaseContext:
    """Shared runtime services and assignment state for all phases."""

    stimuli: StimulusController
    logger: ExperimentLogger
    lick_detector: LickDetector | None
    random_seed: int | None
    rng: random.Random
    scene_assignment: dict[str, Any]
