# -*- coding: utf-8 -*-
"""
tasks/rest_task_fsm.py

Resting-state imaging task (PC2 side).
run() accepts imaging_start_time so the session clock matches the Andor frame count.

IR LED sync pulses
------------------
Four pulses are fired at key synchronisation moments so that the behaviour
log, Andor imaging frames, and body/face camera video share a common set of
timestamps for post-hoc alignment.

  Pulse                    When                                     Blocking?
  ───────────────────────────────────────────────────────────────────────────
  ir_sync_task_start     First line of run() — PC2 pipeline active    Yes
  ir_sync_imaging_start  After imaging_start_time confirmed from PC1   No
  ir_sync_imaging_stop   When recording duration elapses               No
  ir_sync_task_end       After FSM exits — full session complete       Yes

Blocking pulses (start/end) are safe because nothing time-sensitive is
running at those moments.  Non-blocking pulses run in a daemon thread so
the 10 ms FSM update loop is never stalled by the 0.5 s LED sleep.

If ir_led is None (not supplied or hardware absent), all pulse calls are
silently skipped so the task runs identically without the NI-DAQ board.
"""

import threading
import time
from datetime import datetime

from utils.state_machine import StateMachine


class RestTaskFSM(StateMachine):

    def __init__(self, config: dict, logger, ir_led=None):
        """
        Parameters
        ----------
        config : dict
            Loaded from rest_task.yaml.
        logger : TrialLogger
            Behaviour event logger (PC2 side).
        ir_led : IRLEDController or None
            Pass None to disable IR LED sync (e.g. bench testing).
        """
        super().__init__()

        self.config  = config
        self.logger  = logger
        self.ir_led  = ir_led

        self.frame_rate         = config["session"].get("frame_rate", 30)
        self.duration_s         = config["session"]["duration_minutes"] * 60
        self.total_frames       = int(self.duration_s * self.frame_rate)
        self.frames_per_channel = self.total_frames // 3

        # Pulse duration from config; 0.5 s = 15 frames at 30 Hz (unmistakeable)
        self._pulse_duration = config.get("ir_led", {}).get("pulse_duration", 0.5)

        self.session_start = None
        self.state_entered = True
        self.set_state("RECORDING")

    def set_state(self, new_state):
        super().set_state(new_state)
        self.state_entered = True

    # ------------------------------------------------------------------
    # IR LED helpers
    # ------------------------------------------------------------------

    def _pulse(self, label: str, blocking: bool = False):
        """
        Fire an IR LED sync pulse and log the event.

        Parameters
        ----------
        label    : event name written to the behaviour log
        blocking : if True, fire in the calling thread;
                   if False, fire in a daemon thread.
        """
        if self.ir_led is None:
            return

        pulse_duration = self._pulse_duration

        def _fire():
            t_on = self.ir_led.pulse(pulse_duration)
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
    # Main loop
    # ------------------------------------------------------------------

    def run(self, imaging_start_time: float):
        """
        Parameters
        ----------
        imaging_start_time : float
            time.time() captured on PC1 the moment Master-9 fired.
            Returned in the START response as "OK <unix_timestamp>".
        """
        # Pulse 1 — task start (blocking: nothing else running yet)
        self._pulse("ir_sync_task_start", blocking=True)

        self.session_start = imaging_start_time
        elapsed_at_start   = time.time() - self.session_start

        print("=" * 50)
        print("Resting-state scan")
        print(f"  Duration     : {self.config['session']['duration_minutes']} min")
        print(f"  Frame rate   : {self.frame_rate} Hz")
        print(f"  Total frames : {self.total_frames:,}")
        print(f"  Per channel  : {self.frames_per_channel:,} (G/R/B)")
        print(f"  t at task start: {elapsed_at_start:.2f}s (time since imaging start)")
        print("=" * 50)

        # Pulse 2 — imaging start confirmed (non-blocking: FSM loop is about to begin)
        self._pulse("ir_sync_imaging_start", blocking=False)

        while self.state != "DONE":
            self.update()
            time.sleep(0.01)

        # Pulse 4 — task end (blocking: FSM has exited, nothing time-sensitive)
        self._pulse("ir_sync_task_end", blocking=True)

        print("Resting-state scan complete")

    def update(self):
        elapsed = time.time() - self.session_start

        if self.state == "RECORDING":

            if self.state_entered:
                self.state_entered = False
                self.logger.log({
                    "event":         "recording_start",
                    "duration_s":    self.duration_s,
                    "total_frames":  self.total_frames,
                    "frame_rate_hz": self.frame_rate,
                })
                remaining = max(0, self.duration_s - elapsed)
                print(f"Recording — {remaining:.0f}s remaining")
                print("  Press Ctrl+C to abort early")

            if elapsed > 0 and int(elapsed) % 30 == 0:
                if not hasattr(self, "_last_progress_t") or int(elapsed) != self._last_progress_t:
                    self._last_progress_t = int(elapsed)
                    pct       = (elapsed / self.duration_s) * 100
                    remaining = self.duration_s - elapsed
                    frames    = int(elapsed * self.frame_rate)
                    print(f"  [{pct:5.1f}%] t={elapsed:.0f}s | "
                          f"~{remaining:.0f}s remaining | "
                          f"~{frames:,} frames")

            if elapsed >= self.duration_s:
                self.logger.log({
                    "event":           "recording_end",
                    "actual_duration": round(elapsed, 3),
                })
                # Pulse 3 — imaging stop (non-blocking: set_state must not be delayed)
                self._pulse("ir_sync_imaging_stop", blocking=False)
                self.set_state("DONE")

        elif self.state == "DONE":
            pass
