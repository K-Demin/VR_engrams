from __future__ import annotations

from typing import Any

from .base import ExperimentPhase


class DecoderTrainingPhase(ExperimentPhase):
    phase_key = "decoder_training"
    display_name = "decoder training"

    def run(self) -> None:
        baseline_sec = float(self._require("baseline_sec"))
        trial_table = list(self._require("trial_table"))

        self.context.logger.log_event("decoder_baseline_start", duration_sec=baseline_sec)
        self._sleep(baseline_sec)
        self.context.logger.log_event("decoder_baseline_end")

        for idx, trial in enumerate(trial_table):
            cue_frequency_hz = float(trial["cue_frequency_hz"])
            cue_duration_sec = float(trial["cue_duration_sec"])
            cue_side = trial["cue_side"]
            iti_sec = float(trial["iti_sec"])

            self.context.logger.log_event("decoder_trial_start", trial_index=idx, trial=trial)
            self.context.stimuli.deliver_sound(
                frequency_hz=cue_frequency_hz,
                duration_sec=cue_duration_sec,
                side=cue_side,
            )
            self._sleep(iti_sec)
            self.context.logger.log_event("decoder_trial_end", trial_index=idx)


class PreConditioningScenePhase(ExperimentPhase):
    phase_key = "pre_conditioning_scene"
    display_name = "pre-conditioning scene"

    def run(self) -> None:
        scene_key = self._require("scene_key")
        duration_sec = float(self._require("duration_sec"))
        visual_channel_map = dict(self._require("visual_channel_by_scene"))

        assigned_scene = self.context.scene_assignment[scene_key]
        visual_channel = visual_channel_map[assigned_scene]

        self.context.logger.log_event(
            "pre_conditioning_scene_start",
            scene_key=scene_key,
            scene_id=assigned_scene,
            duration_sec=duration_sec,
        )
        self.context.stimuli.deliver_visual(channel=visual_channel, duration_sec=duration_sec)
        self.context.logger.log_event("pre_conditioning_scene_end", scene_key=scene_key, scene_id=assigned_scene)


class FearConditioningPhase(ExperimentPhase):
    phase_key = "fear_conditioning"
    display_name = "fear conditioning"

    def run(self) -> None:
        scene_key = self._require("scene_key")
        visual_channel_map = dict(self._require("visual_channel_by_scene"))
        trial_table = list(self._require("trial_table"))

        assigned_scene = self.context.scene_assignment[scene_key]
        visual_channel = visual_channel_map[assigned_scene]

        self.context.logger.log_event("fear_conditioning_start", scene_key=scene_key, scene_id=assigned_scene)
        for idx, trial in enumerate(trial_table):
            cue_frequency_hz = float(trial["cue_frequency_hz"])
            cue_duration_sec = float(trial["cue_duration_sec"])
            cue_side = trial["cue_side"]
            shock_duration_sec = float(trial["shock_duration_sec"])
            shock_channel = trial["shock_channel"]
            iti_sec = float(trial["iti_sec"])

            self.context.logger.log_event("fear_trial_start", trial_index=idx, trial=trial)
            self.context.stimuli.deliver_visual(channel=visual_channel, duration_sec=cue_duration_sec)
            self.context.stimuli.deliver_sound(
                frequency_hz=cue_frequency_hz,
                duration_sec=cue_duration_sec,
                side=cue_side,
            )
            self.context.stimuli.deliver_shock(
                channel=shock_channel,
                duration_sec=shock_duration_sec,
                amplitude=trial.get("shock_amplitude"),
            )
            self._sleep(iti_sec)
            self.context.logger.log_event("fear_trial_end", trial_index=idx)

        self.context.logger.log_event("fear_conditioning_end", scene_key=scene_key, scene_id=assigned_scene)


class PostConditioningScenePhase(ExperimentPhase):
    phase_key = "post_conditioning_scene"
    display_name = "post-conditioning scene"

    def run(self) -> None:
        scene_key = self._require("scene_key")
        duration_sec = float(self._require("duration_sec"))
        visual_channel_map = dict(self._require("visual_channel_by_scene"))

        assigned_scene = self.context.scene_assignment[scene_key]
        visual_channel = visual_channel_map[assigned_scene]

        self.context.logger.log_event(
            "post_conditioning_scene_start",
            scene_key=scene_key,
            scene_id=assigned_scene,
            duration_sec=duration_sec,
        )
        self.context.stimuli.deliver_visual(channel=visual_channel, duration_sec=duration_sec)
        self.context.logger.log_event("post_conditioning_scene_end", scene_key=scene_key, scene_id=assigned_scene)


class FMRIOptoPhase(ExperimentPhase):
    phase_key = "fmri_opto"
    display_name = "fMRI opto"

    def run(self) -> None:
        cycle_table = list(self._require("cycle_table"))

        self.context.logger.log_event("fmri_opto_start", cycles=len(cycle_table))
        for idx, cycle in enumerate(cycle_table):
            opto_channel = cycle["opto_channel"]
            on_duration_sec = float(cycle["on_duration_sec"])
            off_duration_sec = float(cycle["off_duration_sec"])

            self.context.logger.log_event("fmri_opto_cycle_start", cycle_index=idx, cycle=cycle)
            self.context.stimuli.deliver_opto(
                channel=opto_channel,
                duration_sec=on_duration_sec,
                power_mw=cycle.get("power_mw"),
            )
            self._sleep(off_duration_sec)
            self.context.logger.log_event("fmri_opto_cycle_end", cycle_index=idx)

        self.context.logger.log_event("fmri_opto_end")


def build_scene_assignment(config: dict[str, Any], rng_seed: int | None) -> dict[str, Any]:
    """Resolve scene assignment once and share across all phases."""
    assignment_cfg = dict(config.get("scene_assignment", {}))
    if assignment_cfg:
        return assignment_cfg

    randomization_cfg = dict(config.get("randomization", {}))
    pair = list(randomization_cfg.get("scene_pair", []))
    if len(pair) != 2:
        raise ValueError("Provide either scene_assignment or randomization.scene_pair with 2 scene IDs")

    import random

    rng = random.Random(rng_seed)
    if rng.random() < 0.5:
        return {"target": pair[0], "distractor": pair[1]}
    return {"target": pair[1], "distractor": pair[0]}
