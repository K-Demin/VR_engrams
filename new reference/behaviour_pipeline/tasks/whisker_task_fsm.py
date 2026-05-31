# -*- coding: utf-8 -*-
"""
tasks/whisker_task_fsm.py

Whisker stimulation task (PC2 side).

Session structure:
    - 4 minutes of widefield imaging
    - 4 blocks of air puff stimulation (1 per minute)
    - Each block: N puffs at a fixed rate for block_duration seconds
    - Block start time is randomised within each minute:
          earliest: t = 10s into that minute  (10s baseline guaranteed)
          latest:   t = 50s into that minute  (block ends before next minute)

Timing:
    session_start is set to the moment PC2 sent the START command to PC1,
    which is as close as we can get to when Master-9 actually fired.
    This keeps puff block timing aligned with the Andor frame count.
"""

import random
import time

from utils.state_machine import StateMachine


class WhiskerTaskFSM(StateMachine):

    def __init__(self, config: dict, puff, logger):
        super().__init__()

        self.config = config
        self.puff   = puff
        self.logger = logger

        self.frame_rate   = config["session"].get("frame_rate", 30)
        self.duration_s   = config["session"]["duration_minutes"] * 60

        stim = config["stimulation"]
        self.n_blocks        = stim["n_blocks"]
        self.block_duration  = stim["block_duration"]
        self.puff_rate_hz    = stim["puff_rate_hz"]
        self.block_start_min = stim["block_start_min"]
        self.block_start_max = stim["block_start_max"]

        self.puff_duration = config["timing"]["puff_duration"]
        self.puff_interval = 1.0 / self.puff_rate_hz

        self.block_start_times = self._generate_block_starts()

        self.current_block = 0
        self.session_start = None   # set in run() from imaging_start_time
        self.state_entered = True

        self.set_state("WAITING")

    def _generate_block_starts(self) -> list:
        starts = []
        for minute in range(self.n_blocks):
            offset   = random.uniform(self.block_start_min, self.block_start_max)
            absolute = minute * 60.0 + offset
            starts.append(round(absolute, 3))

        print("Block schedule (absolute seconds from imaging start):")
        for i, t in enumerate(starts):
            offset = t - (i * 60.0)
            print(f"  Block {i+1}: t={t:.1f}s  (offset {offset:.1f}s into minute {i+1})")
        return starts

    def run(self, imaging_start_time: float):
        """
        Parameters
        ----------
        imaging_start_time : float
            time.time() value from the moment PC2 sent START to PC1.
            Used as t=0 so session elapsed time matches the Andor frame count.
        """
        self.session_start = imaging_start_time

        n_puffs_per_block = int(self.block_duration * self.puff_rate_hz)
        elapsed_at_start  = time.time() - self.session_start

        print("=" * 55)
        print("Whisker stimulation task")
        print(f"  Duration      : {self.duration_s:.0f}s ({self.duration_s/60:.0f} min)")
        print(f"  Blocks        : {self.n_blocks}")
        print(f"  Block duration: {self.block_duration}s")
        print(f"  Puff rate     : {self.puff_rate_hz} Hz")
        print(f"  Puffs/block   : {n_puffs_per_block}")
        print(f"  Puff duration : {self.puff_duration * 1000:.0f} ms")
        print(f"  t at task start: {elapsed_at_start:.2f}s (time since imaging start)")
        print("=" * 55)

        while self.state != "DONE":
            self.update()
            time.sleep(0.02)

        print("Whisker stimulation session complete")

    def update(self):
        elapsed = time.time() - self.session_start

        if self.state == "WAITING":

            if self.state_entered:
                self.state_entered = False
                if self.current_block < self.n_blocks:
                    next_t = self.block_start_times[self.current_block]
                    print(f"Waiting for block {self.current_block + 1} "
                          f"at t={next_t:.1f}s  ({max(0, next_t - elapsed):.1f}s from now)")
                else:
                    print("All blocks done — waiting for session end")

            if elapsed >= self.duration_s:
                self.logger.log({"event": "session_end",
                                 "actual_duration": round(elapsed, 3)})
                self.set_state("DONE")
                return

            if self.current_block < self.n_blocks:
                if elapsed >= self.block_start_times[self.current_block]:
                    self.set_state("PUFF_BLOCK")

            self._maybe_print_progress(elapsed)

        elif self.state == "PUFF_BLOCK":

            block_num = self.current_block + 1
            n_puffs   = int(self.block_duration * self.puff_rate_hz)

            print(f"\n>>> BLOCK {block_num}/{self.n_blocks} START "
                  f"| t={elapsed:.1f}s | {n_puffs} puffs @ {self.puff_rate_hz} Hz")

            self.logger.log({
                "event":        "block_start",
                "block":        block_num,
                "t_abs":        round(elapsed, 3),
                "n_puffs":      n_puffs,
                "puff_rate_hz": self.puff_rate_hz,
            })

            block_start = time.perf_counter()
            for i in range(n_puffs):
                target     = block_start + i * self.puff_interval
                sleep_for  = target - time.perf_counter() - 0.002
                if sleep_for > 0:
                    time.sleep(sleep_for)
                while time.perf_counter() < target:
                    pass

                actual_offset = time.perf_counter() - block_start
                self.puff.puff(self.puff_duration)

                print(f"  Puff {i+1}/{n_puffs}  (t+{actual_offset:.3f}s)")
                self.logger.log({
                    "event":      "puff",
                    "block":      block_num,
                    "puff_index": i + 1,
                    "t_in_block": round(actual_offset, 4),
                })

            elapsed_now = time.time() - self.session_start
            print(f"<<< BLOCK {block_num}/{self.n_blocks} END | t={elapsed_now:.1f}s")
            self.logger.log({
                "event": "block_end",
                "block": block_num,
                "t_abs": round(elapsed_now, 3),
            })

            self.current_block += 1
            self.set_state("WAITING")

        elif self.state == "DONE":
            pass

    def _maybe_print_progress(self, elapsed: float):
        tick = int(elapsed) // 30
        if not hasattr(self, "_last_progress_tick"):
            self._last_progress_tick = -1
        if tick != self._last_progress_tick and int(elapsed) % 30 == 0 and elapsed > 0:
            self._last_progress_tick = tick
            pct       = (elapsed / self.duration_s) * 100
            remaining = self.duration_s - elapsed
            frames    = int(elapsed * self.frame_rate)
            print(f"  [{pct:5.1f}%] t={elapsed:.0f}s | "
                  f"~{remaining:.0f}s remaining | "
                  f"~{frames:,} frames | "
                  f"blocks done: {self.current_block}/{self.n_blocks}")
