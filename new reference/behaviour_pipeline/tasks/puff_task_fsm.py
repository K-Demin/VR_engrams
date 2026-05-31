# -*- coding: utf-8 -*-
"""
tasks/puff_task_fsm.py

Air-puff conditioning task FSM — widefield calcium imaging rig.

State diagram
-------------
  BASELINE → ITI → AUDIO → DELAY → PUFF → RESPONSE → ITI (loop)
                                  ↓
                               TIMEOUT → ITI

States
------
  BASELINE   Imaging runs, animal sits quietly. No task events.
             Duration set by timing.baseline in config.

  ITI        Inter-trial interval. Random duration between iti_min and iti_max.
             Easy trials (trial < easy_trials): audio will play on puff side.
             Normal trials: audio side is random.

  AUDIO      Pure tone plays from the chosen speaker (non-blocking).
             Duration: timing.audio_duration.

  DELAY      Silent gap between audio offset and puff delivery.
             Duration: timing.delay.
             Early lick during this window → TIMEOUT.

  PUFF       Air puff delivered via NI-DAQ digital output.
             Duration: timing.puff_duration (typically 50 ms).

  RESPONSE   Lick detection window after puff onset.
             Lick detected → outcome logged, advance to next trial.
             Window expires with no lick → MISS, advance to next trial.

  TIMEOUT    Penalty state after early lick. Animal must wait.
             Duration: timing.timeout.

IR LED sync pulses
------------------
Four pulses are fired at structural session boundaries so that the body
camera video, events.tsv, and frames.tsv share a common set of hardware
timestamps for post-hoc alignment:

  Pulse                  When                                   Blocking?
  ─────────────────────────────────────────────────────────────────────────
  ir_sync_task_start   First line of run() — PC2 pipeline active   Yes
  ir_sync_imaging_start After imaging_start_time passed in          No
  ir_sync_task_end     After all trials complete — session done     Yes

Blocking pulses (start/end) are safe because nothing time-sensitive is
running at those moments. Non-blocking pulses run in a daemon thread so
the 1 ms FSM update loop is never stalled by the 0.5 s LED sleep.

If ir_led is None (not supplied or hardware absent), all pulse calls are
silently skipped — the task runs identically without the NI-DAQ board.

Clock alignment
---------------
run() accepts imaging_start_time (Unix timestamp from PC1, the moment
Master-9 fired). This is passed into logger.start_session() so that
events.tsv onset values share the same t=0 as frames.tsv onset_sec values
on PC1. See trial_logger.py for full details.
"""

import random
import threading
import time
from datetime import datetime

from utils.state_machine import StateMachine


class PuffTaskFSM(StateMachine):

    def __init__(self, config, puff, audio, lick, logger, ir_led=None):
        """
        Parameters
        ----------
        config : dict
            Loaded from puff_task.yaml.
        puff   : PuffController
        audio  : AudioController
        lick   : LickDetector
        logger : TrialLogger
        ir_led : IRLEDController or None
            Pass None to disable IR LED sync (e.g. bench testing).
        """
        super().__init__()

        self.config  = config
        self.puff    = puff
        self.audio   = audio
        self.lick    = lick
        self.logger  = logger
        self.ir_led  = ir_led

        self.trial         = 0
        self.n_trials      = config["session"]["n_trials"]
        self.easy_trials   = config["session"]["easy_trials"]

        self.baseline_duration = config["timing"].get("baseline", 15)
        self.puff_side         = config["hardware"].get("puff_side", "right")

        self._pulse_duration = config.get("ir_led", {}).get("pulse_duration", 0.5)

        self.iti           = 0
        self.audio_side    = None
        self.session_start = None   # set in run() from imaging_start_time
        self.state_entered = True

        self.set_state("BASELINE")

    def set_state(self, new_state):
        super().set_state(new_state)
        self.state_entered = True

    # ------------------------------------------------------------------
    # IR LED sync helpers  (mirrors RestTaskFSM._pulse exactly)
    # ------------------------------------------------------------------

    def _pulse(self, label: str, blocking: bool = False):
        """
        Fire an IR LED sync pulse and log the event.

        Parameters
        ----------
        label    : event name written to the behaviour log
        blocking : if True, fire in the calling thread (safe when FSM is idle);
                   if False, fire in a daemon thread (safe during FSM loop).
        """
        if self.ir_led is None:
            return

        pulse_duration = self._pulse_duration

        def _fire():
            t_on  = self.ir_led.pulse(pulse_duration)
            onset = (t_on - self.session_start) if self.session_start is not None else 0.0
            # UTC time-of-day — directly comparable to Bonsai CsvWriter (Kind=Utc)
            # after applying clock_sync.pc1_minus_pc2_seconds in post-processing
            t_on_utc = datetime.utcfromtimestamp(t_on).strftime("%H:%M:%S.%f")
            self.logger.log({
                "event":    label,
                "duration": pulse_duration,
                "t_on_utc": t_on_utc,
            })
            print(f"  IR LED [{label}] onset={onset:.4f}s  utc={t_on_utc}")

        if blocking:
            _fire()
        else:
            threading.Thread(target=_fire, daemon=True, name=f"IRPulse_{label}").start()

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
            Always play from the puff side so the animal learns that
            sound on the puff side predicts a puff.

        Normal trials:
            Random left or right each trial.
        """
        if self._is_easy_trial():
            self.audio_side = self.puff_side
        else:
            self.audio_side = random.choice(["left", "right"])

    def _audio_freq(self) -> float:
        """Return tone frequency for the current audio side."""
        if self.audio_side == "left":
            return self.config["audio"]["left_freq"]
        return self.config["audio"]["right_freq"]

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, imaging_start_time: float):
        """
        Run the full puff task session.

        Parameters
        ----------
        imaging_start_time : float
            Unix timestamp (time.time()) captured on PC1 the moment
            Master-9 fired — returned by camera_control.start_camera().
            Used as t=0 for the session clock so events.tsv onset values
            align directly with frames.tsv onset_sec values.
        """
        # Pulse 1 — task start (blocking: nothing time-sensitive yet)
        self._pulse("ir_sync_task_start", blocking=True)

        # Anchor session clock to imaging start
        self.session_start = imaging_start_time
        self.logger.start_session(imaging_start_time)

        elapsed_at_start = time.time() - self.session_start

        print("=" * 50)
        print("Puff task")
        print(f"  Baseline   : {self.baseline_duration}s")
        print(f"  Trials     : {self.n_trials}")
        print(f"  Easy trials: {self.easy_trials}")
        print(f"  Puff side  : {self.puff_side}")
        print(f"  t at task start: {elapsed_at_start:.2f}s (since imaging start)")
        print("=" * 50)

        # Pulse 2 — imaging confirmed, about to enter FSM loop (non-blocking)
        self._pulse("ir_sync_imaging_start", blocking=False)

        # Run FSM until all trials are complete
        while not (self.state == "ITI" and self.trial >= self.n_trials):
            self.update()
            time.sleep(0.001)   # 1 ms loop — keeps behaviour responsive

        # Pulse 3 — task end (blocking: FSM has exited, nothing time-sensitive)
        self._pulse("ir_sync_task_end", blocking=True)

        print(f"Session finished — {self.n_trials} trials complete")

    # ------------------------------------------------------------------
    # FSM update
    # ------------------------------------------------------------------

    def update(self):

        state_time = self.time_in_state()

        # ----------------------------------------------------------------
        # BASELINE
        # Imaging runs, animal sits quietly, no task events.
        # ----------------------------------------------------------------
        if self.state == "BASELINE":

            if self.state_entered:
                self.state_entered = False
                print(f"Baseline period — {self.baseline_duration}s")
                self.logger.log({
                    "event":    "baseline_start",
                    "duration": self.baseline_duration,
                })

            if state_time > self.baseline_duration:
                print("Baseline complete — starting trials")
                self.logger.log({"event": "baseline_end"})
                self.set_state("ITI")

        # ----------------------------------------------------------------
        # ITI
        # ----------------------------------------------------------------
        elif self.state == "ITI":

            if self.trial >= self.n_trials:
                # All trials done — run() loop condition catches this
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
                    "duration":   self.iti,
                    "trial_type": trial_type,
                    "iti":        round(self.iti, 3),
                })

            if state_time > self.iti:
                self.set_state("AUDIO")

        # ----------------------------------------------------------------
        # AUDIO
        # ----------------------------------------------------------------
        elif self.state == "AUDIO":

            if self.state_entered:
                self.state_entered = False

                self._choose_audio_side()
                freq = self._audio_freq()

                print(f"  Audio: {self.audio_side} ({freq} Hz)"
                      f"{'  [easy]' if self._is_easy_trial() else ''}")

                self.audio.play_tone(
                    freq     = freq,
                    duration = self.config["timing"]["audio_duration"],
                    side     = self.audio_side
                )

                self.logger.log({
                    "event":      "audio",
                    "trial":      self.trial,
                    "duration":   self.config["timing"]["audio_duration"],
                    "side":       self.audio_side,
                    "freq":       freq,
                    "easy_trial": self._is_easy_trial(),
                })

            if state_time > self.config["timing"]["audio_duration"]:
                self.set_state("DELAY")

        # ----------------------------------------------------------------
        # DELAY
        # Silent gap — early lick triggers timeout penalty.
        # ----------------------------------------------------------------
        elif self.state == "DELAY":

            if self.lick.check_lick():

                print("  Early lick → timeout")

                self.logger.log({
                    "event": "early_lick",
                    "trial": self.trial,
                })

                self.set_state("TIMEOUT")

            elif state_time > self.config["timing"]["delay"]:
                self.set_state("PUFF")

        # ----------------------------------------------------------------
        # PUFF
        # ----------------------------------------------------------------
        elif self.state == "PUFF":

            if self.state_entered:
                self.state_entered = False

                print("  Puff")

                self.puff.puff(self.config["timing"]["puff_duration"])

                self.logger.log({
                    "event":    "puff",
                    "trial":    self.trial,
                    "duration": self.config["timing"]["puff_duration"],
                    "side":     self.puff_side,
                })

            if state_time > self.config["timing"]["puff_duration"]:
                self.set_state("RESPONSE")

        # ----------------------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------------------
        elif self.state == "RESPONSE":

            if self.lick.check_lick():

                print("  Lick detected")

                self.logger.log({
                    "event":   "lick",
                    "trial":   self.trial,
                    "outcome": "hit",
                })

                self.trial += 1
                self.set_state("ITI")

            elif state_time > self.config["timing"]["response_window"]:

                print("  Miss")

                self.logger.log({
                    "event":   "miss",
                    "trial":   self.trial,
                    "outcome": "miss",
                })

                self.trial += 1
                self.set_state("ITI")

        # ----------------------------------------------------------------
        # TIMEOUT
        # ----------------------------------------------------------------
        elif self.state == "TIMEOUT":

            if self.state_entered:
                self.state_entered = False
                timeout = self.config["timing"]["timeout"]
                print(f"  Timeout — {timeout}s")
                self.logger.log({
                    "event":    "timeout_start",
                    "trial":    self.trial,
                    "duration": timeout,
                })

            if state_time > self.config["timing"]["timeout"]:
                self.logger.log({
                    "event": "timeout_end",
                    "trial": self.trial,
                })
                self.trial += 1
                self.set_state("ITI")
