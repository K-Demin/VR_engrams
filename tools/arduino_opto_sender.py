#!/usr/bin/env python3
from __future__ import annotations

"""Send opto-train commands directly to Arduino over serial (no NI required).

Expected Arduino serial protocol:
  PING\n
  POLARITY ACTIVE_HIGH\n
  OFF\n
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


def open_serial_port(serial, port: str, baud: int, timeout_sec: float, reset_on_connect: bool):
    if reset_on_connect:
        return serial.Serial(port, baud, timeout=timeout_sec)

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = timeout_sec
    ser.dtr = False
    ser.rts = False
    ser.open()
    try:
        ser.setDTR(False)
        ser.setRTS(False)
    except Exception:
        pass
    return ser


def read_available_lines(ser, label: str, timeout_sec: float = 0.25) -> int:
    count = 0
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line:
            count += 1
            print(f"[{label}] {line}")
            deadline = time.time() + timeout_sec
    return count


def send_command(ser, command: str, accepted_prefixes: tuple[str, ...], timeout_sec: float = 2.0) -> str:
    command = command.strip()
    print(f"[INFO] sending {command}")
    ser.write(f"{command}\n".encode("ascii"))
    ser.flush()
    saw_line = False
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line:
            saw_line = True
            print(f"[ARDUINO] {line}")
        if any(line.startswith(prefix) for prefix in accepted_prefixes):
            return line
        if line.startswith("ERR"):
            raise RuntimeError(f"Arduino rejected {command}: {line}")
    if not saw_line:
        raise TimeoutError(
            f"No serial response from Arduino after sending {command}. "
            "This usually means the updated opto firmware is not uploaded to this port, "
            "the wrong COM port is selected, or another program has the board in a bad serial state."
        )
    raise TimeoutError(f"Timed out waiting for {accepted_prefixes} after sending {command}")


def configure_safety_state(ser, active_low: bool) -> None:
    polarity = "ACTIVE_LOW" if active_low else "ACTIVE_HIGH"
    try:
        send_command(ser, f"POLARITY {polarity}", ("OK POLARITY",), timeout_sec=1.0)
        send_command(ser, "OFF", ("OK OFF",), timeout_sec=1.0)
        send_command(ser, "PING", ("OK PING",), timeout_sec=1.0)
    except Exception as exc:
        raise RuntimeError(
            "Arduino did not accept safety/polarity commands. Upload tools/arduino_opto_firmware/arduino_opto_firmware.ino "
            "before testing the laser again."
        ) from exc


def send_train(ser, freq_hz: float, pulse_ms: float, duration_sec: float, timeout_sec: float = 2.0) -> None:
    duration_ms = int(round(duration_sec * 1000.0))
    cmd = f"TRAIN {freq_hz:.6f} {pulse_ms:.6f} {duration_ms}\n"
    try:
        send_command(ser, cmd, ("OK TRAIN",), timeout_sec=max(timeout_sec, duration_sec + timeout_sec))
    finally:
        try:
            send_command(ser, "OFF", ("OK OFF",), timeout_sec=1.0)
        except Exception as exc:
            print(f"[WARN] failed to send final OFF: {exc}")


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
    parser.add_argument("--pin", type=int, default=9, help="Arduino firmware opto TTL pin; informational only")
    polarity = parser.add_mutually_exclusive_group()
    polarity.add_argument("--active-low", action="store_true", help="Use active-low laser TTL polarity")
    polarity.add_argument("--active-high", action="store_false", dest="active_low", help="Use active-high laser TTL polarity")
    parser.set_defaults(active_low=False)
    parser.add_argument("--freq-hz", type=float, default=20.0)
    parser.add_argument("--pulse-ms", type=float, default=15.0)
    parser.add_argument("--duration-sec", type=float, default=60.0, help="Used in train mode")
    parser.add_argument("--mode", choices=["train", "block", "off", "ping"], default="train")
    parser.add_argument("--reset-on-connect", action="store_true", help="Allow Arduino serial auto-reset on connect")
    parser.add_argument("--startup-wait-sec", type=float, help="Wait after opening serial before sending commands")
    parser.add_argument("--on-sec", type=float, default=30.0, help="Used in block mode")
    parser.add_argument("--off-sec", type=float, default=30.0, help="Used in block mode")
    parser.add_argument("--total-sec", type=float, default=3600.0, help="Used in block mode")
    args = parser.parse_args()

    serial = _require_pyserial()

    startup_wait_sec = args.startup_wait_sec
    if startup_wait_sec is None:
        startup_wait_sec = 2.0 if args.reset_on_connect else 0.05

    with open_serial_port(
        serial,
        port=args.port,
        baud=int(args.baud),
        timeout_sec=1.0,
        reset_on_connect=bool(args.reset_on_connect),
    ) as ser:
        ser.reset_input_buffer()
        if startup_wait_sec > 0:
            time.sleep(float(startup_wait_sec))
        print(
            f"[INFO] connected to {args.port} @ {args.baud}; "
            f"firmware should drive D{args.pin}; active_low={args.active_low}; "
            f"reset_on_connect={args.reset_on_connect}"
        )
        startup_lines = read_available_lines(ser, "STARTUP")
        if startup_lines == 0 and args.reset_on_connect:
            print(
                "[WARN] no startup banner received. Updated firmware should print "
                "'READY PIN=9 ACTIVE_LOW=0 OFF_LEVEL=LOW' when serial opens."
            )
        elif startup_lines == 0:
            print("[INFO] no startup banner received; this is expected when --reset-on-connect is not used.")
        if args.mode == "ping":
            send_command(ser, "PING", ("OK PING",), timeout_sec=1.0)
            send_command(ser, "STATE", ("STATE",), timeout_sec=1.0)
            return 0
        configure_safety_state(ser, active_low=bool(args.active_low))
        if args.mode == "off":
            return 0
        if args.mode == "train":
            send_train(ser, freq_hz=args.freq_hz, pulse_ms=args.pulse_ms, duration_sec=args.duration_sec)
            return 0
        try:
            run_block_mode(
                ser,
                freq_hz=args.freq_hz,
                pulse_ms=args.pulse_ms,
                on_sec=args.on_sec,
                off_sec=args.off_sec,
                total_sec=args.total_sec,
            )
        finally:
            try:
                send_command(ser, "OFF", ("OK OFF",), timeout_sec=1.0)
            except Exception as exc:
                print(f"[WARN] failed to send final OFF: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
