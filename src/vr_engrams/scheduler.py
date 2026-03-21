from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from .lick_detector import LickDetector
from .logger import ExperimentLogger
from .scene_engine import SceneEngine
from .stimulus_controller import StimulusController

PHASE_ORDER = [
    "decoder",
    "pre-conditioning",
    "fear conditioning",
    "post-conditioning",
    "fMRI opto block design",
]


@dataclass
class ExperimentScheduler:
    """Phase orchestration and trial randomization rules."""

    config: dict[str, Any]
    stimuli: StimulusController
    logger: ExperimentLogger
    lick_detector: LickDetector | None = None

    def run_all_phases(self) -> None:
        self.logger.log_event("experiment_start", phase_order=PHASE_ORDER)
        for phase_name in PHASE_ORDER:
            phase_cfg = self.config.get("phases", {}).get(phase_name, {})
            self.run_phase(phase_name, phase_cfg)
        self.logger.log_event("experiment_complete")

    def run_phase(self, phase_name: str, phase_cfg: dict[str, Any]) -> None:
        if phase_name in {"pre-conditioning", "post-conditioning"}:
            self._run_scene_phase(phase_name, phase_cfg)
            return

        trials = int(phase_cfg.get("trials", 0))
        iti_range = phase_cfg.get("iti_sec", [1.0, 2.0])
        shuffled = bool(phase_cfg.get("randomize_trial_order", True))

        trial_table = list(phase_cfg.get("trial_table", []))
        if trial_table and shuffled:
            random.shuffle(trial_table)

        self.logger.log_event(
            "phase_start",
            phase=phase_name,
            trials=trials,
            randomize_trial_order=shuffled,
        )

        for trial_idx in range(trials):
            trial_spec = trial_table[trial_idx % len(trial_table)] if trial_table else {}
            iti = random.uniform(float(iti_range[0]), float(iti_range[1]))
            self.logger.log_event(
                "trial_start",
                phase=phase_name,
                trial_index=trial_idx,
                iti_sec=round(iti, 4),
                trial_spec=trial_spec,
            )

            self._run_trial_stimuli(phase_name, trial_spec, phase_cfg)

            time.sleep(iti)
            self.logger.log_event("trial_end", phase=phase_name, trial_index=trial_idx)

        self.logger.log_event("phase_end", phase=phase_name)

    def _run_scene_phase(self, phase_name: str, phase_cfg: dict[str, Any]) -> None:
        scene_order = list(phase_cfg.get("scene_order", ["A", "B"]))
        repetitions = int(phase_cfg.get("scene_repetitions", phase_cfg.get("trials", 1)))
        scene_duration_sec = float(phase_cfg.get("scene_duration_sec", phase_cfg.get("cue_duration_sec", 10.0)))

        rng_seed = phase_cfg.get("random_seed", self.config.get("random_seed"))
        scene_engine = SceneEngine(
            logger=self.logger,
            phase_name=phase_name,
            seed=rng_seed,
            dropout_interval_sec=float(phase_cfg.get("dropout_interval_sec", 10.0)),
            dropout_interval_jitter_sec=float(phase_cfg.get("dropout_interval_jitter_sec", 1.0)),
            dropout_duration_min_sec=float(phase_cfg.get("dropout_duration_min_sec", 2.0)),
            dropout_duration_max_sec=float(phase_cfg.get("dropout_duration_max_sec", 4.0)),
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
