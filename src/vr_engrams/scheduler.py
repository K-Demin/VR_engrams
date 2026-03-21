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


@dataclass
class ExperimentScheduler:
    """Sequential phase orchestration controlled entirely by config flags."""

    config: dict[str, Any]
    stimuli: StimulusController
    logger: ExperimentLogger
    lick_detector: LickDetector | None = None

    def run_all_phases(self) -> None:
        random_seed = self.config.get("random_seed")
        if random_seed is not None:
            random_seed = int(random_seed)

        context = PhaseContext(
            stimuli=self.stimuli,
            logger=self.logger,
            lick_detector=self.lick_detector,
            random_seed=random_seed,
            rng=random.Random(random_seed),
            scene_assignment=build_scene_assignment(self.config, random_seed),
        )

        phase_sequence = [
            ("decoder_training", DecoderTrainingPhase),
            ("pre_conditioning_scene", PreConditioningScenePhase),
            ("fear_conditioning", FearConditioningPhase),
            ("post_conditioning_scene", PostConditioningScenePhase),
            ("fmri_opto", FMRIOptoPhase),
        ]

        self.logger.log_event(
            "experiment_start",
            phase_sequence=[phase_key for phase_key, _ in phase_sequence],
            random_seed=random_seed,
            scene_assignment=context.scene_assignment,
        )

        phases_cfg = self.config.get("phases", {})
        for phase_key, phase_cls in phase_sequence:
            phase_cfg = dict(phases_cfg.get(phase_key, {}))
            enabled = bool(phase_cfg.pop("enabled", False))

            if not enabled:
                self.logger.log_event("phase_skipped", phase=phase_key, reason="disabled")
                continue

            phase = phase_cls(context=context, config=phase_cfg)
            self.logger.log_event("phase_start", phase=phase.phase_key, display_name=phase.display_name)
            phase.run()
            self.logger.log_event("phase_end", phase=phase.phase_key)

        self.logger.log_event("experiment_complete")
