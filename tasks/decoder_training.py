# -*- coding: utf-8 -*-
"""Decoder training phase generator and runtime helper."""

from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DecoderEvent:
    """Single decoder-training event."""

    trial_index: int
    stimulus: str
    event_duration_s: float
    iti_s: float


class DecoderTrainingPhase:
    """Implements isolated-stimulus decoder training with anti-streak randomization."""

    def __init__(self, config: Dict, logger=None):
        self.config = config
        self.logger = logger

        session_cfg = config["session"]
        timing_cfg = config["timing"]
        random_cfg = config["randomization"]

        self.no_stim_baseline_s = timing_cfg["no_stim_baseline_s"]
        self.event_duration_min_s = timing_cfg["event_duration_min_s"]
        self.event_duration_max_s = timing_cfg["event_duration_max_s"]
        self.iti_min_s = timing_cfg["iti_min_s"]
        self.iti_max_s = timing_cfg["iti_max_s"]

        self.stimuli = list(session_cfg["stimuli"])
        self.repetitions_per_stimulus = session_cfg["repetitions_per_stimulus"]

        self.max_streak = random_cfg["max_streak"]
        self.seed = random_cfg.get("seed")

        self._rng = random.Random(self.seed)

    def _remaining_by_stimulus(self, events: List[DecoderEvent]) -> Counter:
        used = Counter(evt.stimulus for evt in events)
        return Counter({
            stimulus: self.repetitions_per_stimulus - used[stimulus]
            for stimulus in self.stimuli
        })

    def _streak_len(self, events: List[DecoderEvent], candidate: str) -> int:
        streak = 1
        for evt in reversed(events):
            if evt.stimulus == candidate:
                streak += 1
            else:
                break
        return streak

    def _choose_next_stimulus(self, events: List[DecoderEvent]) -> str:
        remaining = self._remaining_by_stimulus(events)

        allowed = [
            stimulus
            for stimulus in self.stimuli
            if remaining[stimulus] > 0 and self._streak_len(events, stimulus) <= self.max_streak
        ]

        if not allowed:
            allowed = [stimulus for stimulus in self.stimuli if remaining[stimulus] > 0]

        return self._rng.choice(allowed)

    def build_schedule(self) -> List[DecoderEvent]:
        n_events = len(self.stimuli) * self.repetitions_per_stimulus
        events: List[DecoderEvent] = []

        for trial_index in range(n_events):
            stimulus = self._choose_next_stimulus(events)
            events.append(
                DecoderEvent(
                    trial_index=trial_index,
                    stimulus=stimulus,
                    event_duration_s=self._rng.uniform(
                        self.event_duration_min_s,
                        self.event_duration_max_s,
                    ),
                    iti_s=self._rng.uniform(self.iti_min_s, self.iti_max_s),
                )
            )

        return events

    def run(self, sleep: bool = True) -> List[DecoderEvent]:
        schedule = self.build_schedule()

        if self.logger:
            self.logger.log({"event": "no_stim_baseline_start", "duration_s": self.no_stim_baseline_s})
        if sleep:
            time.sleep(self.no_stim_baseline_s)
        if self.logger:
            self.logger.log({"event": "no_stim_baseline_end"})

        for evt in schedule:
            if self.logger:
                self.logger.log(
                    {
                        "event": "stim_on",
                        "trial": evt.trial_index,
                        "stimulus": evt.stimulus,
                        "duration_s": round(evt.event_duration_s, 3),
                    }
                )

            if sleep:
                time.sleep(evt.event_duration_s)

            if self.logger:
                self.logger.log(
                    {
                        "event": "stim_off",
                        "trial": evt.trial_index,
                        "stimulus": evt.stimulus,
                        "iti_s": round(evt.iti_s, 3),
                    }
                )

            if sleep:
                time.sleep(evt.iti_s)

        return schedule
