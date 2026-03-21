from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .lick_detector import LickDetector
from .logger import ExperimentLogger
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
    """Sequential phase orchestration controlled by phase configuration."""

    config: dict[str, Any]
    stimuli: StimulusController
    logger: ExperimentLogger
    lick_detector: LickDetector | None = None
    session_assignment: dict[str, Any] | None = None

    def run_all_phases(self) -> None:
        phase_order = self._resolve_phase_order()
        self._validate_phase_keys(phase_order)

        random_seed = self.config.get("random_seed")
        if random_seed is None:
            random_seed = self.config.get("randomization", {}).get("seed")

        scene_assignment = self.session_assignment
        if scene_assignment is None:
            scene_assignment = build_scene_assignment(self.config, random_seed)

        context = PhaseContext(
            stimuli=self.stimuli,
            logger=self.logger,
            lick_detector=self.lick_detector,
            random_seed=random_seed,
            rng=random.Random(random_seed),
            scene_assignment=scene_assignment,
        )

        self.logger.log_event(
            "experiment_start",
            phase_order=phase_order,
            session_assignment=scene_assignment,
        )

        phases_cfg = self.config.get("phases", {})
        for phase_key in phase_order:
            phase_cfg = phases_cfg.get(phase_key)
            if phase_cfg is None:
                continue
            if not bool(phase_cfg.get("enabled", True)):
                continue
            self.run_phase(context=context, phase_key=phase_key, phase_cfg=phase_cfg)

        self.logger.log_event("experiment_complete")

    def run_phase(self, context: PhaseContext, phase_key: str, phase_cfg: dict[str, Any]) -> None:
        phase_cls = PHASE_HANDLERS.get(phase_key)
        if phase_cls is None:
            raise ValueError(
                f"No registered phase handler for '{phase_key}'. "
                f"Registered handlers: {sorted(PHASE_HANDLERS)}"
            )

        self.logger.log_event("phase_start", phase=phase_key)
        phase = phase_cls(context=context, config=phase_cfg)
        try:
            phase.run()
        finally:
            self.logger.log_event("phase_end", phase=phase_key)

    def _resolve_phase_order(self) -> list[str]:
        phase_order_cfg = self.config.get("phase_order")
        if phase_order_cfg is not None:
            if not isinstance(phase_order_cfg, list) or not all(isinstance(p, str) for p in phase_order_cfg):
                raise ValueError("Config key 'phase_order' must be a list of phase keys (strings).")
            return phase_order_cfg

        phases_cfg = self.config.get("phases", {})
        if isinstance(phases_cfg, dict) and phases_cfg:
            return list(phases_cfg.keys())

        return list(DEFAULT_PHASE_ORDER)

    def _validate_phase_keys(self, phase_order: list[str]) -> None:
        phases_cfg = self.config.get("phases", {})
        if not isinstance(phases_cfg, dict):
            raise ValueError("Config key 'phases' must be a mapping of phase_key -> phase_config.")

        for phase_key in phases_cfg:
            if phase_key not in PHASE_HANDLERS:
                raise ValueError(
                    f"Configured phase '{phase_key}' has no registered handler. "
                    f"Registered handlers: {sorted(PHASE_HANDLERS)}"
                )

        for phase_key in phase_order:
            if phase_key not in PHASE_HANDLERS:
                raise ValueError(
                    f"Phase '{phase_key}' in phase_order has no registered handler. "
                    f"Registered handlers: {sorted(PHASE_HANDLERS)}"
                )
