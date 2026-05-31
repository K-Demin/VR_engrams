# -*- coding: utf-8 -*-
"""
tasks/whisker_localiser_fsm.py

Block-design air puff task for widefield calcium imaging signal testing.

Purpose
-------
Delivers repeated air puffs in discrete ON blocks separated by rest periods,
with no audio cue or lick detection. Intended for localising whisker-evoked
cortical responses during widefield GCaMP imaging.

Session structure
-----------------
  BASELINE → [REST → PUFF_BLOCK] × n_blocks → TAIL_REST → DONE

  BASELINE   : Pre-task imaging with no stimulation.
               Duration: timing.baseline_s.

  REST       : Inter-block rest, no puffs. Duration drawn per rest_mode:
               "fixed"  → always rest_duration_s
               "random" → uniform draw between rest_min_s and rest_max_s,
                          capped so all remaining blocks fit within
                          total_duration_s (see _draw_rest_duration()).

  PUFF_BLOCK : Repeated puffs for block_duration_s. Each puff opens the
               NI-DAQ valve for puff_duration_s, waits until puff_interval_s
               has elapsed since that puff onset, then repeats. The block
               ends when block_duration_s elapses; the in-progress puff
               always completes first. Runs in a background thread.

  TAIL_REST  : Remaining time after the last block until total_duration_s.
               Duration = total_duration_s - elapsed_since_imaging_start.
               Always fills exactly whatever time is left, so every run is
               the same total length regardless of how random rests fell.

  DONE       : Session complete — triggers run() to return.

Total session duration
----------------------
timing.total_duration_s fixes the session length, measured from
imaging_start_time (UTC Unix epoch, moment Master-9 fired on PC1).
The ir_sync_imaging_stop pulse fires when TAIL_REST ends, which is always
at exactly total_duration_s from imaging_start_time.

Rest capping logic
------------------
When drawing a random rest duration, the FSM computes how much time budget
remains for all future rests and puff blocks, then caps the draw:

    budget = total_duration_s - elapsed - blocks_remaining × block_duration_s
             - (blocks_remaining - 1) × min_rest_s  [future inter-block rests]
             - min_rest_s                             [tail rest minimum]
    max_drawable = budget
    draw = min(uniform(rest_min_s, rest_max_s), max_drawable)
    draw = max(draw, min_rest_s)   [never go below minimum]

This guarantees all remaining blocks always fit without any special-casing.

Puff timing
-----------
Uses a single persistent NI-DAQ Task for the full block duration — avoids
~5 ms per-call overhead from PuffController.puff() opening a new Task each
time. Valve is driven directly inside _run_puff_block() background thread.

IR LED sync pulses
------------------
Four pulses fired at structural boundaries (identical to rest_task_fsm):

  Pulse                    When                                      Blocking?
  ────────────────────────────────────────────────────────────────────────────
  ir_sync_task_start     First line of run() — PC2 pipeline active    Yes
  ir_sync_imaging_start  Just before FSM loop — imaging confirmed      No
  ir_sync_imaging_stop   TAIL_REST ends (= total_duration_s elapsed)   No
  ir_sync_task_end       After FSM loop exits — session complete       Yes

If ir_led is None, all pulse calls are silently skipped.

Clock alignment
---------------
run() accepts imaging_start_time (UTC Unix epoch from PC1, moment Master-9
fired). Passed into logger.start_session() so events.tsv onset values share
the same t=0 as frames.tsv onset_sec.
"""

import random
import threading
import time
from datetime import datetime

import nidaqmx

from utils.state_machine import StateMachine


class WhiskerLocaliserFSM(StateMachine):

    def __init__(self, config: dict, logger, ir_led=None):
        """
        Parameters
        ----------
        config : dict
            Loaded from whisker_localiser.yaml.
        logger : TrialLogger
            Behaviour event logger (PC2 side).
        ir_led : IRLEDController or None
            Pass None to disable IR LED sync (bench testing).
        """
        super().__init__()

        self.config  = config
        self.logger  = logger
        self.ir_led  = ir_led

        t = config["timing"]
        self.total_duration_s  = t["total_duration_s"]
        self.baseline_s        = t.get("baseline_s",       30.0)
        self.block_duration_s  = t["block_duration_s"]
        self.puff_duration_s   = t["puff_duration_s"]
        self.puff_interval_s   = t["puff_interval_s"]
        self.rest_mode         = t.get("rest_mode",        "random")
        self.rest_duration_s   = t.get("rest_duration_s",  30.0)
        self.rest_min_s        = t.get("rest_min_s",       20.0)
        self.rest_max_s        = t.get("rest_max_s",       40.0)

        self.puff_channel = config["hardware"]["puff_channel"]

        self.n_blocks    = config["session"]["n_blocks"]
        self.block_index = 0

        self._pulse_duration = config.get("ir_led", {}).get("pulse_duration", 0.5)

        self._current_rest_s      = 0.0
        self._puff_thread         = None
        self._puff_running        = False
        self._puff_count_in_block = 0

        self.session_start = None   # set in run() from imaging_start_time
        self.state_entered = True

        self.set_state("BASELINE")

    def set_state(self, new_state):
        super().set_state(new_state)
        self.state_entered = True

    # ------------------------------------------------------------------
    # IR LED sync helpers  (identical pattern to rest_task_fsm._pulse)
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
            t_on  = self.ir_led.pulse(pulse_duration)
            onset = (t_on - self.session_start) if self.session_start is not None else 0.0
            # UTC time-of-day — comparable to Bonsai CsvWriter (Kind=Utc)
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
    # Rest duration helpers
    # ------------------------------------------------------------------

    def _min_rest(self) -> float:
        """Minimum rest duration — used for budget calculations."""
        return self.rest_duration_s if self.rest_mode == "fixed" else self.rest_min_s

    def _draw_rest_duration(self, blocks_remaining: int) -> float:
        """
        Draw a rest duration for the upcoming inter-block rest, capped so
        that all remaining blocks and a minimum tail rest still fit within
        total_duration_s.

        Parameters
        ----------
        blocks_remaining : int
            Number of puff blocks not yet started, including the one that
            immediately follows this rest period.

        Returns
        -------
        float : rest duration in seconds, always >= min_rest.

        Capping logic
        -------------
        After this rest, the session must still accommodate:
          - blocks_remaining puff blocks
          - (blocks_remaining - 1) inter-block rests at min_rest each
          - 1 tail rest at min_rest

        So the maximum drawable rest is:

            budget = total_duration_s
                     - elapsed_since_imaging_start
                     - blocks_remaining × block_duration_s
                     - (blocks_remaining - 1) × min_rest   [future rests]
                     - min_rest                             [tail rest]

        The draw is clamped to [min_rest, max(budget, min_rest)] to ensure
        the result is always at least min_rest even if the budget is tight.
        """
        elapsed   = time.time() - self.session_start
        min_rest  = self._min_rest()

        # Time that must be reserved for everything after this rest
        reserved  = (
            blocks_remaining * self.block_duration_s    # all remaining blocks
            + (blocks_remaining - 1) * min_rest         # future inter-block rests
            + min_rest                                   # tail rest
        )

        # Maximum this rest can be without causing an overrun
        budget    = self.total_duration_s - elapsed - reserved
        max_draw  = max(budget, min_rest)   # never allow below minimum

        if self.rest_mode == "fixed":
            draw = self.rest_duration_s
        else:
            draw = random.uniform(self.rest_min_s, self.rest_max_s)

        # Cap and floor
        draw = min(draw, max_draw)
        draw = max(draw, min_rest)

        if draw < self.rest_min_s - 0.1:   # warn if capped below desired minimum
            print(
                f"  [WARNING] Rest capped to {draw:.1f}s "
                f"(budget tight — {budget:.1f}s available)"
            )

        return draw

    def _tail_rest_duration(self) -> float:
        """
        Return the tail rest duration = time remaining until total_duration_s.
        Always >= 0. If somehow negative (clock drift), returns 0.
        """
        elapsed = time.time() - self.session_start
        return max(0.0, self.total_duration_s - elapsed)

    # ------------------------------------------------------------------
    # Puff block — runs in background thread
    # ------------------------------------------------------------------

    def _run_puff_block(self, block_index: int):
        """
        Deliver repeated puffs for block_duration_s using a single
        persistent NI-DAQ Task.

        Timing model:
          record puff_onset_wall = time.time()
          valve open → sleep puff_duration_s → valve close
          sleep until puff_onset_wall + puff_interval_s

        The block exits cleanly if block_duration_s elapses between puffs.
        If it elapses mid-puff, the current puff completes first.
        All puff events are logged with onset relative to imaging_start_time.
        """
        block_start = time.time()
        puff_count  = 0

        try:
            with nidaqmx.Task() as task:
                task.do_channels.add_do_chan(self.puff_channel)
                task.write(False)
                time.sleep(0.005)   # brief settle before first puff

                while self._puff_running:
                    # Check block duration before firing
                    if time.time() - block_start >= self.block_duration_s:
                        break

                    # --- Fire puff ---
                    puff_onset_wall = time.time()
                    puff_onset_rel  = puff_onset_wall - self.session_start

                    task.write(True)
                    time.sleep(self.puff_duration_s)
                    task.write(False)

                    puff_count += 1
                    self._puff_count_in_block = puff_count

                    self.logger.log({
                        "event":    "puff",
                        "trial":    block_index,
                        "duration": self.puff_duration_s,
                        "puff_n":   puff_count,
                    })
                    print(
                        f"    Puff {puff_count} | "
                        f"onset={puff_onset_rel:.3f}s | "
                        f"block elapsed="
                        f"{time.time()-block_start:.1f}/{self.block_duration_s:.1f}s"
                    )

                    # --- Wait until next puff onset ---
                    next_onset = puff_onset_wall + self.puff_interval_s
                    while self._puff_running:
                        remaining_in_block = self.block_duration_s - (time.time() - block_start)
                        sleep_to_next      = next_onset - time.time()

                        if remaining_in_block <= 0:
                            self._puff_running = False
                            break
                        if sleep_to_next <= 0:
                            break

                        time.sleep(min(sleep_to_next, remaining_in_block, 0.005))

                task.write(False)   # ensure valve closed

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Puff block thread error: {e}")

        finally:
            self._puff_running = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, imaging_start_time: float):
        """
        Run the full whisker localiser session.

        Parameters
        ----------
        imaging_start_time : float
            UTC Unix timestamp from PC1 at the moment Master-9 fired.
            Used as t=0 for events.tsv onset values.
        """
        # Pulse 1 — task start (blocking: nothing time-sensitive yet)
        self._pulse("ir_sync_task_start", blocking=True)

        self.session_start = imaging_start_time
        self.logger.start_session(imaging_start_time)

        elapsed_at_start = time.time() - self.session_start

        if self.rest_mode == "random":
            rest_desc = f"{self.rest_min_s}–{self.rest_max_s}s random (capped to fit)"
        else:
            rest_desc = f"{self.rest_duration_s}s fixed"

        puffs_per_block = int(self.block_duration_s / self.puff_interval_s)

        # Estimate total session length for display
        min_rest      = self._min_rest()
        min_task_s    = (self.baseline_s
                         + self.n_blocks * (min_rest + self.block_duration_s)
                         + min_rest)
        tail_min_s    = self.total_duration_s - (
                         self.baseline_s
                         + self.n_blocks * (self.rest_max_s + self.block_duration_s))
        tail_max_s    = self.total_duration_s - (
                         self.baseline_s
                         + self.n_blocks * (min_rest + self.block_duration_s))

        print("=" * 58)
        print("Whisker Localiser — block-design puff task")
        print(f"  Total duration : {self.total_duration_s:.0f}s")
        print(f"  Baseline       : {self.baseline_s}s")
        print(f"  Blocks         : {self.n_blocks}  ×  {self.block_duration_s}s")
        print(f"  Puff duration  : {self.puff_duration_s*1000:.0f}ms")
        print(f"  Puff interval  : {self.puff_interval_s}s onset-to-onset")
        print(f"  ~Puffs/block   : {puffs_per_block}")
        print(f"  Rest duration  : {rest_desc}")
        print(f"  Tail rest      : {max(0,tail_min_s):.0f}–{max(0,tail_max_s):.0f}s "
              f"(fills remainder)")
        print(f"  t at task start: {elapsed_at_start:.2f}s (since imaging start)")
        print("=" * 58)

        # Pulse 2 — imaging confirmed, FSM loop about to begin (non-blocking)
        self._pulse("ir_sync_imaging_start", blocking=False)

        # FSM loop
        while self.state != "DONE":
            self.update()
            time.sleep(0.01)   # 10 ms loop — sufficient for REST/BASELINE timing

        # Pulse 4 — task end (blocking: FSM has exited, nothing time-sensitive)
        self._pulse("ir_sync_task_end", blocking=True)

        actual_duration = time.time() - self.session_start
        print(
            f"\nWhisker localiser complete — "
            f"{self.n_blocks} blocks | "
            f"actual duration {actual_duration:.1f}s / {self.total_duration_s:.0f}s target"
        )

    # ------------------------------------------------------------------
    # FSM update
    # ------------------------------------------------------------------

    def update(self):

        state_time = self.time_in_state()

        # ----------------------------------------------------------------
        # BASELINE — imaging runs, no puffs
        # ----------------------------------------------------------------
        if self.state == "BASELINE":

            if self.state_entered:
                self.state_entered = False
                print(f"\nBaseline — {self.baseline_s}s")
                self.logger.log({
                    "event":    "baseline_start",
                    "duration": self.baseline_s,
                })

            if state_time >= self.baseline_s:
                self.logger.log({"event": "baseline_end"})
                print("Baseline complete")
                # Draw first rest — n_blocks remain at this point
                self._current_rest_s = self._draw_rest_duration(
                    blocks_remaining = self.n_blocks
                )
                self.set_state("REST")

        # ----------------------------------------------------------------
        # REST — inter-block rest period, no puffs
        # ----------------------------------------------------------------
        elif self.state == "REST":

            if self.state_entered:
                self.state_entered = False
                blocks_left = self.n_blocks - self.block_index
                elapsed     = time.time() - self.session_start
                print(
                    f"\nRest {self.block_index + 1}/{self.n_blocks} — "
                    f"{self._current_rest_s:.1f}s  "
                    f"(t={elapsed:.1f}s, {self.total_duration_s - elapsed:.1f}s remaining)"
                )
                self.logger.log({
                    "event":    "rest_start",
                    "trial":    self.block_index,
                    "duration": round(self._current_rest_s, 3),
                })

            if state_time >= self._current_rest_s:
                self.logger.log({
                    "event": "rest_end",
                    "trial": self.block_index,
                })
                self.set_state("PUFF_BLOCK")

        # ----------------------------------------------------------------
        # PUFF_BLOCK — launch background puff thread, wait for completion
        # ----------------------------------------------------------------
        elif self.state == "PUFF_BLOCK":

            if self.state_entered:
                self.state_entered        = False
                self._puff_count_in_block = 0
                elapsed = time.time() - self.session_start

                print(
                    f"\nBlock {self.block_index + 1}/{self.n_blocks} — "
                    f"{self.block_duration_s}s puffing | "
                    f"t={elapsed:.1f}s"
                )
                self.logger.log({
                    "event":           "block_start",
                    "trial":           self.block_index,
                    "duration":        self.block_duration_s,
                    "puff_interval_s": self.puff_interval_s,
                    "puff_duration_s": self.puff_duration_s,
                })

                # Launch puff delivery in background thread
                self._puff_running = True
                self._puff_thread  = threading.Thread(
                    target = self._run_puff_block,
                    args   = (self.block_index,),
                    daemon = True,
                    name   = f"PuffBlock{self.block_index}",
                )
                self._puff_thread.start()

            # Wait for puff thread to finish
            if not self._puff_running and self._puff_thread is not None:
                self._puff_thread.join(timeout=1.0)
                self._puff_thread = None

                self.logger.log({
                    "event":           "block_end",
                    "trial":           self.block_index,
                    "puffs_delivered": self._puff_count_in_block,
                })
                print(
                    f"  Block {self.block_index + 1} complete — "
                    f"{self._puff_count_in_block} puffs delivered"
                )

                self.block_index += 1

                if self.block_index >= self.n_blocks:
                    # All blocks done — tail rest fills remaining time
                    self._current_rest_s = self._tail_rest_duration()
                    self.set_state("TAIL_REST")
                else:
                    # Draw next inter-block rest with updated budget
                    blocks_remaining = self.n_blocks - self.block_index
                    self._current_rest_s = self._draw_rest_duration(
                        blocks_remaining = blocks_remaining
                    )
                    self.set_state("REST")

        # ----------------------------------------------------------------
        # TAIL_REST — fills remaining time until total_duration_s
        # ----------------------------------------------------------------
        elif self.state == "TAIL_REST":

            if self.state_entered:
                self.state_entered = False
                elapsed = time.time() - self.session_start
                print(
                    f"\nTail rest — {self._current_rest_s:.1f}s  "
                    f"(t={elapsed:.1f}s → target {self.total_duration_s:.0f}s)"
                )
                self.logger.log({
                    "event":           "tail_rest_start",
                    "duration":        round(self._current_rest_s, 3),
                    "total_elapsed_s": round(elapsed, 3),
                })

            if state_time >= self._current_rest_s:
                actual = round(time.time() - self.session_start, 3)
                self.logger.log({
                    "event":             "tail_rest_end",
                    "actual_duration_s": actual,
                    "target_duration_s": self.total_duration_s,
                })
                # Pulse 3 — imaging stop (non-blocking: set_state must not be delayed)
                # Fires at total_duration_s from imaging_start_time — the same
                # length every run regardless of how random rests fell.
                self._pulse("ir_sync_imaging_stop", blocking=False)
                self.set_state("DONE")

        # ----------------------------------------------------------------
        # DONE — run() loop exits
        # ----------------------------------------------------------------
        elif self.state == "DONE":
            pass
