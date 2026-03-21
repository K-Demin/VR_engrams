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
from .phases.context import PhaseContext
from .phases.protocol_phases import (
    DecoderTrainingPhase,
    FMRIOptoPhase,
    FearConditioningPhase,
    PostConditioningScenePhase,
    PreConditioningScenePhase,
    build_scene_assignment,
)

DEFAULT_PHASE_ORDER: tuple[str, ...] = (
    "decoder_training",
    "pre_conditioning_scene",
    "fear_conditioning",
    "post_conditioning_scene",
    "fmri_opto",
)

PHASE_HANDLERS = {
    "decoder_training": DecoderTrainingPhase,
    "pre_conditioning_scene": PreConditioningScenePhase,
    "fear_conditioning": FearConditioningPhase,
    "post_conditioning_scene": PostConditioningScenePhase,
    "fmri_opto": FMRIOptoPhase,
}


@dataclass
class ExperimentScheduler:
    """Sequential phase orchestration controlled entirely by config."""

    config: dict[str, Any]
    stimuli: StimulusController
    logger: ExperimentLogger
    lick_detector: LickDetector | None = None
    session_assignment: dict[str, Any] | None = None

    def run_all_phases(self) -> None:
        randomization_cfg = dict(self.config.get("randomization", {}))
        seed = randomization_cfg.get("seed")
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

        phase_sequence: list[tuple[str, type]] = [
            ("decoder_training", DecoderTrainingPhase),
            ("pre_conditioning_scene", PreConditioningScenePhase),
            ("fear_conditioning", FearConditioningPhase),
            ("post_conditioning_scene", PostConditioningScenePhase),
            ("fmri_opto", FMRIOptoPhase),
        ]
        self.logger.log_event(
            "experiment_start",
            phase_order=[name for name, _ in phase_sequence],
            scene_assignment=scene_assignment,
        )

        for phase_name, phase_cls in phase_sequence:
            phase_cfg = dict(self.config.get("phases", {}).get(phase_name, {}))
            if not phase_cfg.get("enabled", True):
                self.logger.log_event("phase_skipped", phase=phase_name)
                continue

            self.logger.log_event("phase_start", phase=phase_name)
            phase_cls(context=context, config=phase_cfg).run()
            self.logger.log_event("phase_end", phase=phase_name)

        self.logger.log_event("experiment_complete")

    def _resolve_scene_assignment(self, seed: int | None) -> dict[str, Any]:
        if self.session_assignment:
            if "target" in self.session_assignment and "distractor" in self.session_assignment:
                return {
                    "target": self.session_assignment["target"],
                    "distractor": self.session_assignment["distractor"],
                }
            if "target_scene" in self.session_assignment and "distractor_scene" in self.session_assignment:
                return {
                    "target": self.session_assignment["target_scene"],
                    "distractor": self.session_assignment["distractor_scene"],
                }

        return build_scene_assignment(self.config, seed)
