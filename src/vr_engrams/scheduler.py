from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .lick_detector import LickDetector
from .logger import ExperimentLogger
from .phases import (
    DecoderTrainingPhase,
    FMRIOptoPhase,
    FearConditioningPhase,
    PhaseContext,
    PostConditioningScenePhase,
    PreConditioningScenePhase,
    build_scene_assignment,
)
from .stimulus_controller import StimulusController

PHASE_ORDER = ["decoder", "pre", "fear", "post", "fmri"]

PHASE_CLASS_BY_KEY = {
    DecoderTrainingPhase.phase_key: DecoderTrainingPhase,
    PreConditioningScenePhase.phase_key: PreConditioningScenePhase,
    FearConditioningPhase.phase_key: FearConditioningPhase,
    PostConditioningScenePhase.phase_key: PostConditioningScenePhase,
    FMRIOptoPhase.phase_key: FMRIOptoPhase,
}

PHASE_ALIASES = {
    "decoder_training": "decoder",
    "pre_conditioning_scene": "pre",
    "fear_conditioning": "fear",
    "post_conditioning_scene": "post",
    "fmri_opto": "fmri",
}


@dataclass
class ExperimentScheduler:
    """Sequential phase orchestration using protocol phase classes only."""

    config: dict[str, Any]
    stimuli: StimulusController
    logger: ExperimentLogger
    lick_detector: LickDetector | None = None
    session_assignment: dict[str, Any] | None = None

    def run_all_phases(self) -> None:
        seed = self._random_seed()
        rng = random.Random(seed)
        scene_assignment = self._resolve_scene_assignment(seed)

        context = PhaseContext(
            stimuli=self.stimuli,
            logger=self.logger,
            lick_detector=self.lick_detector,
            random_seed=seed,
            rng=rng,
            scene_assignment=scene_assignment,
        )

        phase_blocks = self._normalized_phase_blocks()

        self.logger.log_event(
            "experiment_start",
            phase_order=PHASE_ORDER,
            available_phases=sorted(phase_blocks.keys()),
            random_seed=seed,
            scene_assignment=scene_assignment,
        )

        for phase_name in PHASE_ORDER:
            phase_cfg = phase_blocks.get(phase_name)
            if phase_cfg is None:
                self.logger.log_event("phase_skipped", phase=phase_name, reason="missing_config")
                continue
            if not bool(phase_cfg.get("enabled", True)):
                self.logger.log_event("phase_skipped", phase=phase_name, reason="disabled")
                continue

            phase_class = PHASE_CLASS_BY_KEY[phase_name]
            self.logger.log_event("phase_start", phase=phase_name, phase_class=phase_class.__name__)
            phase_class(context=context, config=phase_cfg).run()
            self.logger.log_event("phase_end", phase=phase_name, phase_class=phase_class.__name__)

        self.logger.log_event("experiment_complete")

    def _random_seed(self) -> int | None:
        if "random_seed" in self.config:
            return self.config.get("random_seed")
        return dict(self.config.get("randomization", {})).get("seed")

    def _resolve_scene_assignment(self, seed: int | None) -> dict[str, Any]:
        if self.session_assignment and {"target_scene", "distractor_scene"}.issubset(self.session_assignment):
            return {
                "target": self.session_assignment["target_scene"],
                "distractor": self.session_assignment["distractor_scene"],
            }
        return build_scene_assignment(self.config, rng_seed=seed)

    def _normalized_phase_blocks(self) -> dict[str, dict[str, Any]]:
        raw_phases = dict(self.config.get("phases", {}))
        normalized: dict[str, dict[str, Any]] = {}

        for raw_key, raw_value in raw_phases.items():
            canonical_key = PHASE_ALIASES.get(raw_key, raw_key)
            if canonical_key in PHASE_CLASS_BY_KEY:
                normalized[canonical_key] = dict(raw_value)

        return normalized
