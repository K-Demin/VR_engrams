# -*- coding: utf-8 -*-
"""
tasks/audio_lick_reward_fsm.py

Audio → Lick → Reward association task — 3 levels.

Level 1 — Pavlovian (tone predicts reward)
    Tone plays on fixed interval. After `tone_reward_delay` seconds,
    water is delivered automatically. Animal learns tone → reward.

Level 2 — Operant (tone cues lick for reward)
    Tone plays on fixed interval. Opens a `response_window` during which
    a lick triggers reward delivery. Miss = no reward, move on.

Level 3 — Probabilistic operant (variable timing + chance)
    Tone plays with variable ITI. Lick within response window has
    `reward_probability` chance of triggering reward. Builds robust
    lick behaviour resistant to extinction.

Usage:
    python main_audio_lick_reward.py configs/audio_lick_reward.yaml --animal m01 --level 2
"""

import random
import time

from utils.state_machine import StateMachine


class AudioLickRewardFSM(StateMachine):

    def __init__(self, config, valve, lick, audio, logger):
        """
        Parameters
        ----------
        config : dict         — loaded from audio_lick_reward.yaml
        valve  : WaterValve
        lick   : LickDetector
        audio  : AudioController
        logger : TrialLogger
        """
        super().__init__()

        self.config = config
        self.valve  = valve
        self.lick   = lick
        self.audio  = audio
        self.logger = logger

        cfg = config["session"]
        self.level    = cfg["level"]
        self.n_trials = cfg["n_trials"]

        t = config["timing"]
        self.tone_interval    = t["tone_interval"]        # fixed ITI (levels 1 & 2)
        self.iti_min          = t.get("iti_min", 25.0)   # variable ITI min (level 3)
        self.iti_max          = t.get("iti_max", 35.0)   # variable ITI max (level 3)
        self.tone_duration    = t["tone_duration"]
        self.tone_reward_delay = t["tone_reward_delay"]  # delay from tone offset → reward
        self.response_window  = t["response_window"]
        self.reward_prob      = t.get("reward_probability", 1.0)
        self.valve_duration_ms = config["hardware"]["valve_duration_ms"]
        self.refractory       = t.get("refractory", 1.0)

        a = config["audio"]
        self.tone_freq = a["tone_freq"]
        self.tone_side = a.get("tone_side", "both")
        self.volume    = a.get("volume", 0.25)

        self.trial         = 0
        self.rewards_given = 0
        self.current_iti   = self.tone_interval
        self.state_entered = True

        self.set_state("ITI")

    def set_state(self, new_state):
        super().set_state(new_state)
        self.state_entered = True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_iti(self) -> float:
        if self.level == 3:
            return random.uniform(self.iti_min, self.iti_max)
        return self.tone_interval

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        print("=" * 50)
        print(f"Audio-Lick-Reward | Level {self.level}")
        print(f"  Trials:        {self.n_trials}")
        print(f"  Tone:          {self.tone_freq} Hz ({self.tone_side})")
        print(f"  Tone duration: {self.tone_duration}s")
        if self.level == 1:
            print(f"  Reward delay:  {self.tone_reward_delay}s after tone offset")
            print(f"  Interval:      {self.tone_interval}s (fixed)")
        elif self.level == 2:
            print(f"  Response win:  {self.response_window}s")
            print(f"  Interval:      {self.tone_interval}s (fixed)")
        elif self.level == 3:
            print(f"  Response win:  {self.response_window}s")
            print(f"  ITI:           {self.iti_min}–{self.iti_max}s (variable)")
            print(f"  Probability:   {self.reward_prob*100:.0f}%")
        print("=" * 50)

        while self.trial < self.n_trials:
            self.update()
            time.sleep(0.001)

        print(f"Session complete — {self.rewards_given}/{self.n_trials} rewards delivered")

    def update(self):
        state_time = self.time_in_state()

        # ---------------------------------------------------------------
        # ITI — wait before tone
        # ---------------------------------------------------------------
        if self.state == "ITI":

            if self.state_entered:
                self.state_entered = False
                self.current_iti   = self._next_iti()

                trial_type = {1: "pavlovian", 2: "operant", 3: "probabilistic"}[self.level]
                print(f"\nTrial {self.trial + 1}/{self.n_trials} | {trial_type} | ITI {self.current_iti:.1f}s")

                self.logger.log({
                    "event":      "iti_start",
                    "trial":      self.trial,
                    "iti":        round(self.current_iti, 2),
                    "level":      self.level
                })

            if state_time >= self.current_iti:
                self.set_state("TONE")

        # ---------------------------------------------------------------
        # TONE — play cue
        # ---------------------------------------------------------------
        elif self.state == "TONE":

            if self.state_entered:
                self.state_entered = False

                self.audio.play_tone(
                    freq     = self.tone_freq,
                    duration = self.tone_duration,
                    side     = self.tone_side,
                    volume   = self.volume
                )

                print(f"  🔊 Tone: {self.tone_freq} Hz ({self.tone_duration}s)")
                self.logger.log({
                    "event": "tone",
                    "trial": self.trial,
                    "freq":  self.tone_freq,
                    "side":  self.tone_side
                })

            if state_time >= self.tone_duration:
                # After tone offset → different next states per level
                if self.level == 1:
                    self.set_state("REWARD_DELAY")
                else:
                    self.set_state("RESPONSE")

        # ---------------------------------------------------------------
        # REWARD_DELAY — fixed pause before automatic reward (Level 1)
        # ---------------------------------------------------------------
        elif self.state == "REWARD_DELAY":

            if state_time >= self.tone_reward_delay:
                self.set_state("DELIVER")

        # ---------------------------------------------------------------
        # RESPONSE — wait for lick within response window (Levels 2 & 3)
        # ---------------------------------------------------------------
        elif self.state == "RESPONSE":

            if self.lick.check_lick():

                self.logger.log({"event": "lick", "trial": self.trial})
                print(f"  Lick detected")

                if self.level == 2:
                    self.set_state("DELIVER")

                elif self.level == 3:
                    # Probabilistic gate
                    if random.random() < self.reward_prob:
                        print(f"  Reward granted ({self.reward_prob*100:.0f}%)")
                        self.logger.log({"event": "reward_granted", "trial": self.trial})
                        self.set_state("DELIVER")
                    else:
                        print(f"  Reward withheld ({self.reward_prob*100:.0f}%)")
                        self.logger.log({"event": "reward_withheld", "trial": self.trial})
                        self.set_state("MISS")

            elif state_time >= self.response_window:
                print(f"  MISS — no lick in {self.response_window}s")
                self.logger.log({"event": "miss", "trial": self.trial})
                self.set_state("MISS")

        # ---------------------------------------------------------------
        # DELIVER — open valve
        # ---------------------------------------------------------------
        elif self.state == "DELIVER":

            if self.state_entered:
                self.state_entered = False

                self.valve.deliver(self.valve_duration_ms)
                self.rewards_given += 1

                print(f"  💧 Reward ({self.rewards_given} total) | {self.valve_duration_ms:.0f}ms")
                self.logger.log({
                    "event":         "reward",
                    "trial":         self.trial,
                    "valve_ms":      self.valve_duration_ms,
                    "rewards_given": self.rewards_given
                })

                self.trial += 1
                self.set_state("ITI")

        # ---------------------------------------------------------------
        # MISS — no reward, advance to next trial
        # ---------------------------------------------------------------
        elif self.state == "MISS":

            if self.state_entered:
                self.state_entered = False
                self.trial += 1

            if state_time >= self.refractory:
                self.set_state("ITI")
