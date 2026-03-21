# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 16:35:24 2026

@author: JoshB
"""

import random
import time

from utils.state_machine import StateMachine


class PuffTaskFSM(StateMachine):

    def __init__(self, config, puff, audio, lick, logger):

        super().__init__()

        self.config    = config
        self.puff      = puff
        self.audio     = audio
        self.lick      = lick
        self.logger    = logger

        self.trial       = 0
        self.n_trials    = config["session"]["n_trials"]
        self.easy_trials = config["session"]["easy_trials"]

        # Baseline duration (seconds) - camera runs but no task
        self.baseline_duration = config["timing"].get("baseline", 15)

        # Side the puff is delivered to - used to define easy trial audio side
        # Set in config as hardware.puff_side: "left" or "right"
        self.puff_side = config["hardware"].get("puff_side", "right")

        self.iti           = 0
        self.audio_side    = None
        self.state_entered = True

        self.set_state("BASELINE")

    def set_state(self, new_state):
        super().set_state(new_state)
        self.state_entered = True

    # ------------------------------------------------------------------
    # Trial type helpers
    # ------------------------------------------------------------------

    def _is_easy_trial(self) -> bool:
        """Returns True if current trial should be an easy (congruent) trial."""
        return self.trial < self.easy_trials

    def _choose_audio_side(self):
        """
        Choose which speaker plays this trial.

        Easy trials (trial < easy_trials):
            Always play from the puff side — animal learns
            sound on puff side means puff is coming.

        Normal trials:
            Random left or right each trial.
        """
        if self._is_easy_trial():
            self.audio_side = self.puff_side
        else:
            self.audio_side = random.choice(["left", "right"])

    def _audio_freq(self) -> float:
        """Return frequency for the current audio side."""
        if self.audio_side == "left":
            return self.config["audio"]["left_freq"]
        return self.config["audio"]["right_freq"]

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):

        print("=" * 45)
        print(f"Starting puff task")
        print(f"  Baseline:    {self.baseline_duration}s")
        print(f"  Trials:      {self.n_trials}")
        print(f"  Easy trials: {self.easy_trials}")
        print("=" * 45)

        # Run until all trials complete (BASELINE state counts down first)
        while not (self.state == "ITI" and self.trial >= self.n_trials):
            self.update()
            time.sleep(0.001)   # 1ms loop — keeps behaviour responsive

        print("Session finished")

    def update(self):

        state_time = self.time_in_state()

        # -------------------------
        # BASELINE
        # Imaging runs, animal sits quietly, no task events
        # -------------------------
        if self.state == "BASELINE":

            if self.state_entered:
                self.state_entered = False
                print(f"Baseline period — {self.baseline_duration}s")
                self.logger.log({"event": "baseline_start"})

            if state_time > self.baseline_duration:
                print("Baseline complete — starting task")
                self.logger.log({"event": "baseline_end"})
                self.set_state("ITI")

        # -------------------------
        # ITI
        # -------------------------
        elif self.state == "ITI":

            if self.trial >= self.n_trials:
                # All trials done — run() loop condition will catch this
                return

            if self.state_entered:
                self.state_entered = False

                self.iti = random.uniform(
                    self.config["timing"]["iti_min"],
                    self.config["timing"]["iti_max"]
                )

                trial_type = "easy" if self._is_easy_trial() else "normal"
                print(f"Trial {self.trial + 1}/{self.n_trials} | {trial_type} | ITI {self.iti:.2f}s")

                self.logger.log({
                    "event":      "trial_start",
                    "trial":      self.trial,
                    "trial_type": trial_type,
                    "iti":        round(self.iti, 3)
                })

            if state_time > self.iti:
                self.set_state("AUDIO")

        # -------------------------
        # AUDIO
        # -------------------------
        elif self.state == "AUDIO":

            if self.state_entered:
                self.state_entered = False

                self._choose_audio_side()
                freq = self._audio_freq()

                print(f"  Audio: {self.audio_side} ({freq}Hz) {'[easy]' if self._is_easy_trial() else ''}")

                self.audio.play_tone(
                    freq     = freq,
                    duration = self.config["timing"]["audio_duration"],
                    side     = self.audio_side
                )

                self.logger.log({
                    "event":      "audio",
                    "trial":      self.trial,
                    "side":       self.audio_side,
                    "freq":       freq,
                    "easy_trial": self._is_easy_trial()
                })

            if state_time > self.config["timing"]["audio_duration"]:
                self.set_state("DELAY")

        # -------------------------
        # DELAY
        # No licking allowed — early lick → timeout
        # -------------------------
        elif self.state == "DELAY":

            if self.lick.check_lick():

                print("  EARLY LICK → timeout")

                self.logger.log({
                    "event": "early_lick",
                    "trial": self.trial
                })

                self.set_state("TIMEOUT")

            elif state_time > self.config["timing"]["delay"]:
                self.set_state("PUFF")

        # -------------------------
        # PUFF
        # -------------------------
        elif self.state == "PUFF":

            if self.state_entered:
                self.state_entered = False

                print("  Puff")

                self.puff.puff(self.config["timing"]["puff_duration"])

                self.logger.log({
                    "event": "puff",
                    "trial": self.trial
                })

            if state_time > self.config["timing"]["puff_duration"]:
                self.set_state("RESPONSE")

        # -------------------------
        # RESPONSE
        # -------------------------
        elif self.state == "RESPONSE":

            lick_detected = self.lick.check_lick()

            if lick_detected:

                print("  LICK DETECTED")

                self.logger.log({
                    "event":   "lick",
                    "trial":   self.trial,
                    "outcome": "lick"
                })

                self.trial += 1
                self.set_state("ITI")

            elif state_time > self.config["timing"]["response_window"]:

                print("  MISS")

                self.logger.log({
                    "event":   "miss",
                    "trial":   self.trial,
                    "outcome": "miss"
                })

                self.trial += 1
                self.set_state("ITI")

        # -------------------------
        # TIMEOUT
        # -------------------------
        elif self.state == "TIMEOUT":

            if self.state_entered:
                self.state_entered = False
                print(f"  Timeout {self.config['timing']['timeout']}s")

            if state_time > self.config["timing"]["timeout"]:
                self.trial += 1
                self.set_state("ITI")