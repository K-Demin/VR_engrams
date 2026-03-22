#!/usr/bin/env python3
from __future__ import annotations

"""Send opto-train commands directly to Arduino over serial (no NI required).

Expected Arduino serial protocol:
  TRAIN <freq_hz> <pulse_ms> <duration_ms>\n
Arduino should reply:
  OK TRAIN\n

Block-mode command from this script repeatedly sends TRAIN / waits OFF windows.
"""

import argparse
import time


def _require_pyserial():
    try:
        import serial  # type: ignore
    except Exception as exc:  # pragma: no cover - env-dependent
        raise RuntimeError(f"pyserial is required: {exc}") from exc
    return serial


def send_train(ser, freq_hz: float, pulse_ms: float, duration_sec: float, timeout_sec: float = 2.0) -> None:
    duration_ms = int(round(duration_sec * 1000.0))
    cmd = f"TRAIN {freq_hz:.6f} {pulse_ms:.6f} {duration_ms}\n"
    ser.write(cmd.encode("ascii"))
    ser.flush()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line:
            print(f"[ARDUINO] {line}")
        if line.startswith("OK TRAIN"):
            return
    raise TimeoutError("Timed out waiting for 'OK TRAIN' from Arduino")


def run_block_mode(ser, freq_hz: float, pulse_ms: float, on_sec: float, off_sec: float, total_sec: float) -> None:
    elapsed = 0.0
    cycle = 0
    while elapsed < total_sec:
        on_win = min(on_sec, total_sec - elapsed)
        if on_win > 0:
            print(f"[INFO] cycle={cycle} ON {on_win:.3f}s")
            send_train(ser, freq_hz=freq_hz, pulse_ms=pulse_ms, duration_sec=on_win)
            elapsed += on_win
        off_win = min(off_sec, total_sec - elapsed)
        if off_win > 0:
            print(f"[INFO] cycle={cycle} OFF {off_win:.3f}s")
            time.sleep(off_win)
            elapsed += off_win
        cycle += 1
    print(f"[INFO] done: elapsed={elapsed:.3f}s cycles={cycle}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct Arduino opto train sender (serial)")
    parser.add_argument("--port", default="COM3", help="Arduino serial port (default COM3)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--freq-hz", type=float, default=20.0)
    parser.add_argument("--pulse-ms", type=float, default=15.0)
    parser.add_argument("--duration-sec", type=float, default=60.0, help="Used in train mode")
    parser.add_argument("--mode", choices=["train", "block"], default="train")
    parser.add_argument("--on-sec", type=float, default=30.0, help="Used in block mode")
    parser.add_argument("--off-sec", type=float, default=30.0, help="Used in block mode")
    parser.add_argument("--total-sec", type=float, default=3600.0, help="Used in block mode")
    args = parser.parse_args()

    serial = _require_pyserial()

    with serial.Serial(args.port, args.baud, timeout=1.0) as ser:
        time.sleep(2.0)  # allow board reset
        ser.reset_input_buffer()
        print(f"[INFO] connected to {args.port} @ {args.baud}")
        if args.mode == "train":
            send_train(ser, freq_hz=args.freq_hz, pulse_ms=args.pulse_ms, duration_sec=args.duration_sec)
            return 0
        run_block_mode(
            ser,
            freq_hz=args.freq_hz,
            pulse_ms=args.pulse_ms,
            on_sec=args.on_sec,
            off_sec=args.off_sec,
            total_sec=args.total_sec,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
