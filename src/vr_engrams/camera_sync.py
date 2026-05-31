from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from statistics import median
from typing import Any


@dataclass
class CameraSyncClient:
    """Client for the PC1 camera listener protocol used by the reference rig."""

    host: str
    port: int
    timeout_ping_sec: float = 5.0
    timeout_command_sec: float = 20.0

    def _send_command(self, command: str, timeout: float) -> tuple[str, float, float]:
        payload = f"{command}\n".encode("utf-8")
        with socket.create_connection((self.host, int(self.port)), timeout=float(timeout)) as sock:
            sock.settimeout(float(timeout))
            t_send = time.time()
            sock.sendall(payload)
            response = sock.recv(4096).decode("utf-8", errors="replace").strip()
            t_receive = time.time()
        return response, t_send, t_receive

    def ping(self) -> bool:
        response, _, _ = self._send_command("PING", timeout=self.timeout_ping_sec)
        return response.upper().startswith("PONG")

    def measure_clock_offset(self, n_samples: int = 5) -> dict[str, Any]:
        offsets: list[float] = []
        rtts_ms: list[float] = []
        raw_samples: list[dict[str, float]] = []

        for _ in range(max(1, int(n_samples))):
            response, t_send, t_receive = self._send_command("TIMESYNC", timeout=self.timeout_ping_sec)
            parts = response.split()
            response_type = parts[0].upper() if parts else ""
            if response_type == "TIMESYNC" and len(parts) >= 2:
                pc1_time = float(parts[1])
                pc1_timeofday = parts[2] if len(parts) >= 3 else None
            elif response_type == "TIME" and len(parts) == 2:
                pc1_time = float(parts[1])
                pc1_timeofday = None
            else:
                raise ValueError(f"Malformed TIMESYNC response from camera server: {response!r}")

            midpoint_pc2 = (t_send + t_receive) / 2.0
            rtt_ms = (t_receive - t_send) * 1000.0
            offset = pc1_time - midpoint_pc2
            offsets.append(offset)
            rtts_ms.append(rtt_ms)
            raw_samples.append(
                {
                    "pc1_time": pc1_time,
                    "pc2_send_time": t_send,
                    "pc2_receive_time": t_receive,
                    "pc1_minus_pc2_seconds": offset,
                    "round_trip_ms": rtt_ms,
                    "pc1_timeofday": pc1_timeofday,
                }
            )

        return {
            "pc1_minus_pc2_seconds": float(median(offsets)),
            "rtt_ms_median": float(median(rtts_ms)),
            "rtt_ms_min": float(min(rtts_ms)),
            "n_samples": len(offsets),
            "samples": raw_samples,
            "pc1_imaging_start_unix": None,
            "pc1_imaging_start_timeofday": None,
        }

    def start(self, session_path_pc1: str, bids_stem: str = "", led_cycle: Any | None = None) -> tuple[bool, float | None]:
        led_payload = "" if led_cycle is None else ",".join(str(item) for item in led_cycle)
        response, _, _ = self._send_command(
            f"START {session_path_pc1}|{bids_stem}|{led_payload}",
            timeout=self.timeout_command_sec,
        )
        parts = response.split()
        if len(parts) == 2 and parts[0].upper() == "OK":
            return True, float(parts[1])
        if response.upper().startswith("ERR"):
            return False, None
        raise ValueError(f"Malformed START response from camera server: {response!r}")

    def stop(self) -> bool:
        response, _, _ = self._send_command("STOP", timeout=self.timeout_command_sec)
        return response.upper().startswith("OK")
