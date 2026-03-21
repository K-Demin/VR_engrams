from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .lick_detector import LickDetector
from .logger import ExperimentLogger
from .scene_engine import SceneEngine
from .stimulus_controller import StimulusController


@dataclass
class ExperimentScheduler:
    """Sequential phase orchestration controlled entirely by config flags."""

    config: dict[str, Any]
    stimuli: StimulusController
    logger: ExperimentLogger
    lick_detector: LickDetector | None = None
    session_assignment: dict[str, Any] | None = None

    def run_all_phases(self) -> None:
        self.logger.log_event(
            "experiment_start",
            phase_order=PHASE_ORDER,
            session_assignment=self.session_assignment,
        )
        for phase_name in PHASE_ORDER:
            phase_cfg = self.config.get("phases", {}).get(phase_name, {})
            self.run_phase(phase_name, phase_cfg)
        self.logger.log_event("experiment_complete")

    def run_phase(self, phase_name: str, phase_cfg: dict[str, Any]) -> None:
        target_scene = None
        distractor_scene = None
        if self.session_assignment:
            target_scene = self.session_assignment.get("target_scene")
            distractor_scene = self.session_assignment.get("distractor_scene")

        trials = int(phase_cfg.get("trials", 0))
        iti_range = phase_cfg.get("iti_sec", [1.0, 2.0])
        shuffled = bool(phase_cfg.get("randomize_trial_order", True))

        phase_sequence = [
            ("decoder_training", DecoderTrainingPhase),
            ("pre_conditioning_scene", PreConditioningScenePhase),
            ("fear_conditioning", FearConditioningPhase),
            ("post_conditioning_scene", PostConditioningScenePhase),
            ("fmri_opto", FMRIOptoPhase),
        ]

        self.logger.log_event(
            "phase_start",
            phase=phase_name,
            trials=trials,
            randomize_trial_order=shuffled,
            target_scene=target_scene,
            distractor_scene=distractor_scene,
        )

        for trial_idx in range(trials):
            trial_spec = dict(trial_table[trial_idx % len(trial_table)]) if trial_table else {}
            if target_scene is not None:
                trial_spec.setdefault("target_scene", target_scene)
            if distractor_scene is not None:
                trial_spec.setdefault("distractor_scene", distractor_scene)
            iti = random.uniform(float(iti_range[0]), float(iti_range[1]))
            self.logger.log_event(
                "trial_start",
                phase=phase_name,
                trial_index=trial_idx,
                iti_sec=round(iti, 4),
                trial_spec=trial_spec,
            )

        self.logger.log_event(
            "phase_start",
            phase=phase_name,
            scene_order=scene_order,
            scene_repetitions=repetitions,
            scene_duration_sec=scene_duration_sec,
        )

        condition_index = 0
        for repetition in range(repetitions):
            for scene_label in scene_order:
                scene_engine.run_condition(
                    scene_label=scene_label,
                    condition_index=condition_index,
                    repetition=repetition,
                    duration_sec=scene_duration_sec,
                )
                condition_index += 1

        self.logger.log_event("phase_end", phase=phase_name)

    def _run_trial_stimuli(self, phase_name: str, trial_spec: dict[str, Any], phase_cfg: dict[str, Any]) -> None:
        # Shared cue handling
        cue_duration = float(trial_spec.get("cue_duration_sec", phase_cfg.get("cue_duration_sec", 0.5)))
        cue_frequency = float(trial_spec.get("cue_frequency_hz", phase_cfg.get("cue_frequency_hz", 8000)))
        cue_side = trial_spec.get("cue_side", phase_cfg.get("cue_side", "both"))
        self.stimuli.deliver_sound(cue_frequency, cue_duration, side=cue_side)

        if phase_name == "fear conditioning" and phase_cfg.get("shock_enabled", True):
            self.stimuli.deliver_shock(
                channel=phase_cfg.get("shock_channel", "shock"),
                duration_sec=float(phase_cfg.get("shock_duration_sec", 0.3)),
                amplitude=phase_cfg.get("shock_amplitude", None),
            )

        if phase_name == "fMRI opto block design":
            self.stimuli.deliver_opto(
                channel=phase_cfg.get("opto_channel", "opto"),
                duration_sec=float(phase_cfg.get("opto_duration_sec", 1.0)),
                power_mw=phase_cfg.get("opto_power_mw", None),
            )

        if phase_cfg.get("puff_enabled", False):
            self.stimuli.deliver_puff(
                channel=phase_cfg.get("puff_channel", "puff"),
                duration_sec=float(phase_cfg.get("puff_duration_sec", 0.05)),
            )
