# -*- coding: utf-8 -*-
"""
tasks/lick_training_fsm.py

Lick training task — 3 levels of increasing difficulty.

Level 1 — Free reward
    Water is delivered automatically every `free_reward_interval` seconds.
    Animal learns that licking produces water; no contingency yet.

Level 2 — Lick-triggered reward (with delay)
    Water is delivered `reward_delay` seconds after a lick is detected.
    Animal must lick to get water; builds lick→reward association.

Level 3 — Probabilistic reward
    Water is delivered with probability `reward_probability` after a lick.
    Introduces uncertainty; prevents extinction of licking.

Usage:
    python main_lick_training.py configs/lick_training.yaml --animal m01 --level 1
"""

import random
import time

from utils.state_machine import StateMachine


class LickTrainingFSM(StateMachine):

    def __init__(self, config, valve, lick, logger):
        """
        Parameters
        ----------
        config : dict   — loaded from lick_training.yaml
        valve  : WaterValve
        lick   : LickDetector
        logger : TrialLogger
        """
        super().__init__()

        self.config = config
        self.valve  = valve
        self.lick   = lick
        self.logger = logger

        cfg = config["session"]
        self.level           = cfg["level"]
        self.n_rewards       = cfg["n_rewards"]      # stop after this many deliveries
        self.valve_duration_ms = config["hardware"]["valve_duration_ms"]

        t = config["timing"]
        self.free_interval   = t["free_reward_interval"]   # Level 1
        self.reward_delay    = t["reward_delay"]            # Level 2
        self.reward_prob     = t.get("reward_probability", 1.0)  # Level 3

        self.rewards_given   = 0
        self.lick_time       = None   # when the triggering lick was detected
        self.state_entered   = True

        self.set_state("WAITING")

    def set_state(self, new_state):
        super().set_state(new_state)
        self.state_entered = True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        print("=" * 45)
        print(f"Lick training | Level {self.level}")
        print(f"  Rewards:     {self.n_rewards}")
        print(f"  Valve open:  {self.valve_duration_ms:.0f} ms")
        if self.level == 1:
            print(f"  Interval:    {self.free_interval}s (free reward)")
        elif self.level == 2:
            print(f"  Reward delay: {self.reward_delay}s after lick")
        elif self.level == 3:
            print(f"  Probability:  {self.reward_prob*100:.0f}%")
        print("=" * 45)

        while self.rewards_given < self.n_rewards:
            self.update()
            time.sleep(0.001)

        print(f"Training complete — {self.rewards_given} rewards delivered")

    def update(self):
        state_time = self.time_in_state()

        # ---------------------------------------------------------------
        # WAITING — idle between events
        # ---------------------------------------------------------------
        if self.state == "WAITING":

            if self.state_entered:
                self.state_entered = False
                self.logger.log({
                    "event":         "waiting",
                    "trial":         self.rewards_given,
                    "rewards_given": self.rewards_given
                })

            # Level 1: timed free reward
            if self.level == 1:
                if state_time >= self.free_interval:
                    self.set_state("DELIVER")

            # Level 2 & 3: wait for a lick
            else:
                if self.lick.check_lick():
                    self.lick_time = time.time()
                    self.logger.log({
                        "event": "lick_detected",
                        "trial": self.rewards_given
                    })
                    print(f"  Lick detected (reward #{self.rewards_given + 1})")

                    if self.level == 2:
                        self.set_state("DELAY")
                    elif self.level == 3:
                        self.set_state("PROB_CHECK")

        # ---------------------------------------------------------------
        # DELAY — wait before delivering reward (Level 2)
        # ---------------------------------------------------------------
        elif self.state == "DELAY":

            if state_time >= self.reward_delay:
                self.set_state("DELIVER")

        # ---------------------------------------------------------------
        # PROB_CHECK — probabilistic gate (Level 3)
        # ---------------------------------------------------------------
        elif self.state == "PROB_CHECK":

            if self.state_entered:
                self.state_entered = False

                if random.random() < self.reward_prob:
                    print(f"  Reward granted ({self.reward_prob*100:.0f}% chance)")
                    self.logger.log({"event": "reward_granted", "trial": self.rewards_given})
                    self.set_state("DELAY")   # still apply delay before valve
                else:
                    print(f"  Reward withheld ({self.reward_prob*100:.0f}% chance)")
                    self.logger.log({"event": "reward_withheld", "trial": self.rewards_given})
                    self.set_state("REFRACTORY")

        # ---------------------------------------------------------------
        # DELIVER — open valve
        # ---------------------------------------------------------------
        elif self.state == "DELIVER":

            if self.state_entered:
                self.state_entered = False

                self.valve.deliver(self.valve_duration_ms)
                self.rewards_given += 1

                print(f"  💧 Reward delivered ({self.rewards_given}/{self.n_rewards}) | {self.valve_duration_ms:.0f}ms")
                self.logger.log({
                    "event":         "reward",
                    "trial":         self.rewards_given,
                    "valve_ms":      self.valve_duration_ms,
                    "rewards_given": self.rewards_given
                })

                self.set_state("REFRACTORY")

        # ---------------------------------------------------------------
        # REFRACTORY — brief lockout to prevent double-counting
        # ---------------------------------------------------------------
        elif self.state == "REFRACTORY":

            if self.state_entered:
                self.state_entered = False
                refractory = self.config["timing"].get("refractory", 1.0)

            if state_time >= self.config["timing"].get("refractory", 1.0):
                self.set_state("WAITING")
