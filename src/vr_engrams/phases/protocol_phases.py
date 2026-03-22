from __future__ import annotations

import random
import threading
import time
from typing import Any

from .base import ExperimentPhase


class DecoderTrainingPhase(ExperimentPhase):
    phase_key = "decoder"
    display_name = "decoder"

    def run(self) -> None:
        trials = self._build_trials()
        randomized = bool(self.config.get("randomized", self.config.get("randomize_trial_order", True)))

        ordered_trials = list(trials)
        if randomized:
            self.context.rng.shuffle(ordered_trials)
        if bool(self.config.get("anti_streak_randomization", False)):
            ordered_trials = self._apply_anti_streak(ordered_trials, max_streak=2)

        self.context.logger.log_event(
            "decoder_start",
            trial_count=len(ordered_trials),
            randomized=randomized,
        )

        for idx, trial in enumerate(ordered_trials):
            condition = str(trial["condition"])
            duration_sec = float(trial["duration_sec"])
            iti_sec = float(trial["iti_sec"])

            self.context.logger.log_event("decoder_trial_start", trial_index=idx, trial=trial)

            if condition in {"screen_a", "screen_b"}:
                channel = str(trial.get("visual_channel", condition))
                self.context.stimuli.deliver_visual(channel=channel, duration_sec=duration_sec)
            elif condition in {"sound_a", "sound_b"}:
                self.context.stimuli.deliver_sound(
                    frequency_hz=float(trial.get("frequency_hz", 8000.0)),
                    duration_sec=duration_sec,
                    side=str(trial.get("side", "both")),
                )
            elif condition in {"whisker_a", "whisker_b"}:
                self.context.stimuli.deliver_puff(
                    channel=str(trial.get("puff_channel", "puff")),
                    duration_sec=duration_sec,
                )
            else:
                self._sleep(duration_sec)

            self._sleep(iti_sec)
            self.context.logger.log_event("decoder_trial_end", trial_index=idx)

        self.context.logger.log_event("decoder_end")

    def _build_trials(self) -> list[dict[str, Any]]:
        if "trials" in self.config:
            return list(self.config["trials"])

        conditions = list(self._require("conditions"))
        reps = int(self.config.get("reps_per_condition", 1))
        stimuli_cfg = dict(self.config.get("_stimuli", {}))
        audio_cfg = dict(stimuli_cfg.get("audio", {}))
        event_range = self.config.get("event_duration_sec", [2.0, 10.0])
        iti_range = self.config.get("iti_sec", [2.0, 10.0])
        event_min, event_max = float(event_range[0]), float(event_range[1])
        iti_min, iti_max = float(iti_range[0]), float(iti_range[1])

        trials: list[dict[str, Any]] = []
        for condition in conditions:
            for _ in range(reps):
                trial: dict[str, Any] = {
                    "condition": condition,
                    "duration_sec": self.context.rng.uniform(event_min, event_max),
                    "iti_sec": self.context.rng.uniform(iti_min, iti_max),
                }
                if condition == "sound_a":
                    trial["frequency_hz"] = float(
                        self.config.get("sound_a_frequency_hz", audio_cfg.get("sound_a_frequency_hz", 8000.0))
                    )
                elif condition == "sound_b":
                    trial["frequency_hz"] = float(
                        self.config.get("sound_b_frequency_hz", audio_cfg.get("sound_b_frequency_hz", 12000.0))
                    )
                elif condition == "screen_a":
                    trial["visual_channel"] = str(self.config.get("screen_a_channel", "screen_a"))
                elif condition == "screen_b":
                    trial["visual_channel"] = str(self.config.get("screen_b_channel", "screen_b"))
                elif condition in {"whisker_a", "whisker_b"}:
                    trial["puff_channel"] = str(self.config.get("puff_channel", "puff"))
                trials.append(trial)
        return trials

    @staticmethod
    def _apply_anti_streak(trials: list[dict[str, Any]], max_streak: int) -> list[dict[str, Any]]:
        if not trials:
            return trials
        trials = list(trials)
        for _ in range(len(trials) * 3):
            streak = 1
            ok = True
            for i in range(1, len(trials)):
                if trials[i]["condition"] == trials[i - 1]["condition"]:
                    streak += 1
                    if streak > max_streak:
                        ok = False
                        swap_idx = next(
                            (
                                j
                                for j in range(i + 1, len(trials))
                                if trials[j]["condition"] != trials[i]["condition"]
                            ),
                            None,
                        )
                        if swap_idx is not None:
                            trials[i], trials[swap_idx] = trials[swap_idx], trials[i]
                        break
                else:
                    streak = 1
            if ok:
                return trials
        return trials


class PreConditioningScenePhase(ExperimentPhase):
    phase_key = "pre"
    display_name = "pre"

    def run(self) -> None:
        self._run_blocks(label="pre")

    def _run_blocks(self, label: str) -> None:
        block_table = list(self._require("block_table"))
        repeats = int(self.config.get("blocks_per_condition", 1))
        randomized = bool(self.config.get("randomize_trial_order", True))
        blocks = block_table * repeats
        if randomized:
            self.context.rng.shuffle(blocks)

        self.context.logger.log_event(f"{label}_start", block_count=len(blocks))
        for block_idx, block in enumerate(blocks):
            self._run_single_scene_block(label=label, block_idx=block_idx, block=block)
        self.context.logger.log_event(f"{label}_end", block_count=len(blocks))

    def _run_single_scene_block(self, label: str, block_idx: int, block: dict[str, Any]) -> None:
        condition = str(block["condition"])
        duration_sec = float(block["duration_sec"])
        if condition == "empty":
            self.context.logger.log_event(f"{label}_empty_scene", block_index=block_idx, duration_sec=duration_sec)
            self._sleep(duration_sec)
            return
        if condition == "opto_sham":
            self.context.logger.log_event(f"{label}_opto_sham", block_index=block_idx, duration_sec=duration_sec)
            self._sleep(duration_sec)
            return
        if condition == "active_opto":
            self.context.logger.log_event(f"{label}_active_opto_start", block_index=block_idx, duration_sec=duration_sec)
            self.context.stimuli.deliver_opto(channel="opto", duration_sec=duration_sec)
            self.context.logger.log_event(f"{label}_active_opto_end", block_index=block_idx)
            return

        scene_key = "target" if condition == "target" else "distractor"
        self._run_scene_with_dropout(label=label, block_idx=block_idx, scene_key=scene_key, duration_sec=duration_sec)

    def _run_scene_with_dropout(self, label: str, block_idx: int, scene_key: str, duration_sec: float) -> None:
        scene_id = str(self.context.scene_assignment[scene_key])
        randomization_cfg = dict(self.config.get("_randomization", {}))
        dropout_cfg = dict(randomization_cfg.get("dropout", {}))
        dropout_interval_sec = float(dropout_cfg.get("interval_sec", 10.0))
        dropout_range = list(dropout_cfg.get("dropout_duration_sec", [2.0, 4.0]))
        dropout_modalities = list(dropout_cfg.get("dropped_modalities", ["screen", "sound", "whisker"]))
        self.context.logger.log_event(
            f"{label}_scene_start", block_index=block_idx, scene_key=scene_key, scene_id=scene_id, duration_sec=duration_sec
        )

        elapsed = 0.0
        while elapsed < duration_sec:
            chunk = min(dropout_interval_sec, duration_sec - elapsed)
            drop_modality = self.context.rng.choice(dropout_modalities)
            drop_for = min(self.context.rng.uniform(float(dropout_range[0]), float(dropout_range[1])), chunk)
            keep_for = max(0.0, chunk - drop_for)
            self.context.logger.log_event(
                f"{label}_dropout",
                block_index=block_idx,
                scene_id=scene_id,
                drop_modality=drop_modality,
                drop_for_sec=drop_for,
                keep_for_sec=keep_for,
            )
            self._deliver_scene_chunk(scene_id=scene_id, duration_sec=keep_for, dropped=drop_modality)
            if drop_for > 0:
                self._deliver_scene_chunk(scene_id=scene_id, duration_sec=drop_for, dropped=None)
            elapsed += chunk

        self.context.logger.log_event(f"{label}_scene_end", block_index=block_idx, scene_key=scene_key, scene_id=scene_id)

    def _deliver_scene_chunk(self, scene_id: str, duration_sec: float, dropped: str | None) -> None:
        if duration_sec <= 0:
            return
        stimuli_cfg = dict(self.config.get("_stimuli", {}))
        audio_cfg = dict(stimuli_cfg.get("audio", {}))
        sound_freq = (
            float(audio_cfg.get("sound_a_frequency_hz", 8000.0))
            if scene_id.upper() == "A"
            else float(audio_cfg.get("sound_b_frequency_hz", 12000.0))
        )
        workers: list[threading.Thread] = []

        if dropped != "screen":
            workers.append(
                threading.Thread(
                    target=self.context.stimuli.deliver_visual,
                    kwargs={"channel": f"screen_{scene_id.lower()}", "duration_sec": duration_sec},
                    daemon=True,
                )
            )
        if dropped != "sound":
            workers.append(
                threading.Thread(
                    target=self.context.stimuli.deliver_sound,
                    kwargs={"frequency_hz": sound_freq, "duration_sec": duration_sec, "side": "both"},
                    daemon=True,
                )
            )
        if dropped != "whisker":
            workers.append(
                threading.Thread(
                    target=self.context.stimuli.deliver_puff,
                    kwargs={"channel": "puff", "duration_sec": min(0.05, duration_sec)},
                    daemon=True,
                )
            )

        chunk_start = time.perf_counter()
        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join(timeout=max(0.001, duration_sec))

        elapsed = time.perf_counter() - chunk_start
        if elapsed < duration_sec:
            self._sleep(duration_sec - elapsed)


class FearConditioningPhase(ExperimentPhase):
    phase_key = "fear"
    display_name = "fear"

    def run(self) -> None:
        shock_enabled = bool(self._require("shock_enabled"))
        if not shock_enabled:
            raise ValueError("fear_conditioning requires shock_enabled=true before run")

        scene_key = str(self.config.get("scene_key", "target"))
        scene_id = str(self.context.scene_assignment[scene_key])
        shock_channel = str(self.config.get("shock_channel", "shock"))
        shock_duration_sec = float(self.config.get("shock_duration_sec", 0.2))
        amplitude = self.config.get("shock_amplitude_mA")

        duration_range_min = self.config.get("target_scene_duration_min", [6.0, 8.0])
        total_duration_sec = self.context.rng.uniform(float(duration_range_min[0]) * 60.0, float(duration_range_min[1]) * 60.0)
        shock_count_range = self.config.get("shocks_per_session", [3, 5])
        shock_count = self.context.rng.randint(int(shock_count_range[0]), int(shock_count_range[1]))
        spacing_sec = self.config.get("shock_spacing_sec", [30.0, 60.0])

        shock_times: list[float] = []
        t = self.context.rng.uniform(float(spacing_sec[0]), float(spacing_sec[1]))
        while t < total_duration_sec and len(shock_times) < shock_count:
            shock_times.append(t)
            t += self.context.rng.uniform(float(spacing_sec[0]), float(spacing_sec[1]))

        self.context.logger.log_event(
            "fear_conditioning_start",
            scene_key=scene_key,
            scene_id=scene_id,
            total_duration_sec=total_duration_sec,
            planned_shock_times_sec=shock_times,
        )

        elapsed = 0.0
        for idx, shock_t in enumerate(shock_times):
            pre = max(0.0, shock_t - elapsed)
            if pre > 0:
                self.context.stimuli.deliver_visual(channel=f"screen_{scene_id.lower()}", duration_sec=pre)
                elapsed += pre
            self.context.stimuli.deliver_shock(channel=shock_channel, duration_sec=shock_duration_sec, amplitude=amplitude)
            elapsed += shock_duration_sec
            self.context.logger.log_event("fear_shock_end", shock_index=idx, shock_time_sec=shock_t)

        remaining = max(0.0, total_duration_sec - elapsed)
        if remaining > 0:
            self.context.stimuli.deliver_visual(channel=f"screen_{scene_id.lower()}", duration_sec=remaining)

        self.context.logger.log_event("fear_end", scene_key=scene_key, scene_id=scene_id)


class PostConditioningScenePhase(PreConditioningScenePhase):
    phase_key = "post"
    display_name = "post"

    def run(self) -> None:
        self._run_blocks(label="post")


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
    pair = list(randomization_cfg.get("scene_pair", randomization_cfg.get("allowed_scenes", [])))
    if len(pair) != 2:
        raise ValueError("Provide either scene_assignment or randomization.scene_pair with 2 scene IDs")

    import random

    rng = random.Random(rng_seed)
    if rng.random() < 0.5:
        return {"target": pair[0], "distractor": pair[1]}
    return {"target": pair[1], "distractor": pair[0]}
