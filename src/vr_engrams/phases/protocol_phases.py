from __future__ import annotations

from typing import Any

from .base import ExperimentPhase


class DecoderTrainingPhase(ExperimentPhase):
    phase_key = "decoder"
    display_name = "decoder"

    def run(self) -> None:
        trials = list(self._require("trials"))
        randomized = bool(self.config.get("randomized", True))

        ordered_trials = list(trials)
        if randomized:
            self.context.rng.shuffle(ordered_trials)

        self.context.logger.log_event(
            "decoder_start",
            trial_count=len(ordered_trials),
            randomized=randomized,
        )

        for idx, trial in enumerate(ordered_trials):
            cue_frequency_hz = float(trial["cue_frequency_hz"])
            cue_duration_sec = float(trial["cue_duration_sec"])
            cue_side = str(trial.get("cue_side", "both"))
            iti_sec = float(trial.get("iti_sec", self.config.get("default_iti_sec", 1.0)))

            self.context.logger.log_event("decoder_trial_start", trial_index=idx, trial=trial)
            # Isolated stimulus: only cue + ITI, no additional modalities.
            self.context.stimuli.deliver_sound(
                frequency_hz=cue_frequency_hz,
                duration_sec=cue_duration_sec,
                side=cue_side,
            )
            self._sleep(iti_sec)
            self.context.logger.log_event("decoder_trial_end", trial_index=idx)

        self.context.logger.log_event("decoder_end")


class PreConditioningScenePhase(ExperimentPhase):
    phase_key = "pre"
    display_name = "pre"

    def run(self) -> None:
        self._run_scene_with_dropout(label="pre")

    def _run_scene_with_dropout(self, label: str) -> None:
        scene_key = str(self.config.get("scene_key", "target"))
        scene_duration_sec = float(self._require("duration_sec"))
        visual_channel_map = dict(self._require("visual_channel_by_scene"))

        dropout_probability = float(self.config.get("dropout_probability", 0.0))
        dropout_chunk_sec = float(self.config.get("dropout_chunk_sec", scene_duration_sec))
        dropout_chunk_sec = max(0.001, dropout_chunk_sec)

        assigned_scene = self.context.scene_assignment[scene_key]
        visual_channel = visual_channel_map[assigned_scene]

        self.context.logger.log_event(
            f"{label}_scene_start",
            scene_key=scene_key,
            scene_id=assigned_scene,
            duration_sec=scene_duration_sec,
            dropout_probability=dropout_probability,
            dropout_chunk_sec=dropout_chunk_sec,
        )

        elapsed = 0.0
        chunk_idx = 0
        while elapsed < scene_duration_sec:
            remaining = scene_duration_sec - elapsed
            chunk_duration_sec = min(dropout_chunk_sec, remaining)
            is_dropout = self.context.rng.random() < dropout_probability

            self.context.logger.log_event(
                f"{label}_scene_chunk",
                chunk_index=chunk_idx,
                duration_sec=chunk_duration_sec,
                dropout=is_dropout,
            )

            if is_dropout:
                self._sleep(chunk_duration_sec)
            else:
                self.context.stimuli.deliver_visual(channel=visual_channel, duration_sec=chunk_duration_sec)

            elapsed += chunk_duration_sec
            chunk_idx += 1

        self.context.logger.log_event(f"{label}_scene_end", scene_key=scene_key, scene_id=assigned_scene)


class FearConditioningPhase(ExperimentPhase):
    phase_key = "fear"
    display_name = "fear"

    def run(self) -> None:
        shock_enabled = bool(self._require("shock_enabled"))
        if not shock_enabled:
            raise ValueError("fear_conditioning requires shock_enabled=true before run")

        scene_key = self._require("scene_key")
        visual_channel_map = dict(self._require("visual_channel_by_scene"))
        trial_table = list(self._require("trial_table"))
        configured_outputs = set(self.context.stimuli.daq.do_tasks.keys())
        invalid_channels = sorted(
            {
                trial.get("shock_channel")
                for trial in trial_table
                if not isinstance(trial.get("shock_channel"), str)
                or not trial.get("shock_channel", "").strip()
                or trial.get("shock_channel") not in configured_outputs
            }
        )
        if invalid_channels:
            raise ValueError(
                "fear_conditioning requires valid shock output mapping before run; "
                f"invalid shock_channel entries: {invalid_channels}"
            )

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
            if not isinstance(shock_channel, str) or not shock_channel.strip():
                raise ValueError(f"fear_conditioning trial {idx} has invalid shock_channel mapping: {shock_channel!r}")

            self.context.stimuli.deliver_shock(
                channel=shock_channel,
                duration_sec=shock_duration_sec,
                amplitude=shock_cfg.get("shock_amplitude"),
            )

            if post_shock_sec > 0:
                self.context.stimuli.deliver_visual(channel=visual_channel, duration_sec=post_shock_sec)

            self.context.logger.log_event("fear_shock_end", shock_index=idx)

        self.context.logger.log_event("fear_end", scene_key=scene_key, scene_id=assigned_scene)


class PostConditioningScenePhase(PreConditioningScenePhase):
    phase_key = "post"
    display_name = "post"

    def run(self) -> None:
        self._run_scene_with_dropout(label="post")

        scene_key = str(self.config.get("scene_key", "target"))
        active_opto_scene_key = str(self.config.get("active_opto_scene_key", scene_key))
        active_scene = self.context.scene_assignment[active_opto_scene_key]
        current_scene = self.context.scene_assignment[scene_key]

        if current_scene != active_scene:
            self.context.logger.log_event(
                "post_opto_skipped",
                reason="scene_mismatch",
                scene_key=scene_key,
                active_opto_scene_key=active_opto_scene_key,
                current_scene=current_scene,
                active_scene=active_scene,
            )
            return

        opto_duration_sec = float(self.config.get("opto_duration_sec", 0.0))
        if opto_duration_sec <= 0:
            self.context.logger.log_event("post_opto_skipped", reason="non_positive_duration")
            return

        opto_channel = str(self.config.get("opto_channel", "opto"))
        power_mw = self.config.get("opto_power_mw")

        self.context.logger.log_event(
            "post_opto_start",
            scene_key=scene_key,
            active_opto_scene_key=active_opto_scene_key,
            duration_sec=opto_duration_sec,
        )
        self.context.stimuli.deliver_opto(
            channel=opto_channel,
            duration_sec=opto_duration_sec,
            power_mw=float(power_mw) if power_mw is not None else None,
        )
        self.context.logger.log_event("post_opto_end")


class FMRIOptoPhase(ExperimentPhase):
    phase_key = "fmri"
    display_name = "fMRI"

    def run(self) -> None:
        total_duration_sec = float(self._require("total_duration_sec"))
        on_duration_sec = float(self.config.get("on_duration_sec", 30.0))
        off_duration_sec = float(self.config.get("off_duration_sec", 30.0))
        opto_channel = str(self.config.get("opto_channel", "opto"))
        power_mw = self.config.get("opto_power_mw")

        elapsed = 0.0
        cycle_index = 0

        self.context.logger.log_event(
            "fmri_start",
            total_duration_sec=total_duration_sec,
            on_duration_sec=on_duration_sec,
            off_duration_sec=off_duration_sec,
        )

        while elapsed < total_duration_sec:
            on_window_sec = min(on_duration_sec, total_duration_sec - elapsed)
            if on_window_sec > 0:
                self.context.logger.log_event(
                    "fmri_cycle_on",
                    cycle_index=cycle_index,
                    duration_sec=on_window_sec,
                )
                self.context.stimuli.deliver_opto(
                    channel=opto_channel,
                    duration_sec=on_window_sec,
                    power_mw=float(power_mw) if power_mw is not None else None,
                )
                elapsed += on_window_sec

            off_window_sec = min(off_duration_sec, total_duration_sec - elapsed)
            if off_window_sec > 0:
                self.context.logger.log_event(
                    "fmri_cycle_off",
                    cycle_index=cycle_index,
                    duration_sec=off_window_sec,
                )
                self._sleep(off_window_sec)
                elapsed += off_window_sec

            cycle_index += 1

        self.context.logger.log_event("fmri_end", cycles=cycle_index, elapsed_sec=elapsed)


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
