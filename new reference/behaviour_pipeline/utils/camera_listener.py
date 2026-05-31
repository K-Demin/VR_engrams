# -*- coding: utf-8 -*-
"""
utils/camera_listener.py  —  PC1 (camera control computer)
===========================================================
Listens for TCP commands from PC2 and drives:
  - Master-9 (Zyla + LEDs via serial → CH1 master trigger)
  - FrameLogger (software-side widefield frame timestamps)

Bonsai is assumed to be already running (started manually via the GUI
before this script). Python does not launch or stop Bonsai.

Commands
--------
    PING
        → "PONG"

    TIMESYNC <pc2_timestamp>
        Clock offset measurement. PC1 echoes back the PC2 timestamp
        plus its own current time so PC2 can estimate the clock difference.
        → "TIMESYNC <pc2_timestamp> <pc1_timestamp>"

    START <func_dir_pc1>|<bids_stem>|<led_cycle>
        Fire Master-9 CH1, start FrameLogger.
        → "OK <unix_timestamp>"

    STOP
        Stop Master-9 + FrameLogger → "OK"

    EXIT
        STOP + shutdown server → "OK"

START payload format
--------------------
    "<func_dir_pc1>|<bids_stem>|<led_cycle>"

    func_dir_pc1 : full path to func/ directory on PC1
    bids_stem    : BIDS filename stem with trailing underscore
                   e.g. "sub-m01_ses-1_task-rest_run-1_"
    led_cycle    : comma-separated LED names matching Master-9 paradigm
                   Current paradigm: "Green,Blue"
                   Omitting this field falls back to "Green,Blue".

    FrameLogger writes: <func_dir_pc1>/<bids_stem>frames.tsv

Master-9 paradigm (pre-programmed in GUI)
------------------------------------------
    CH1 → master trigger  (Python fires this; routing cascades to slaves)
    CH3 → Andor camera    (20 Hz, D=40ms, I=50ms,  N=7200)
    CH6 → Green LED       (10 Hz, D=20ms, I=100ms, N=3600)
    CH7 → Blue LED        (10 Hz, D=45ms, I=100ms, N=3600)
    CH5 → OFF (Red LED not used)

Workflow (each session)
-----------------------
    1. Open Bonsai GUI → set output path → click Play
    2. Run camera_listener.py  (this script)
    3. Run pipeline on PC2  (sends START, runs task, sends STOP)
"""

import socket
import threading
import logging
import signal
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hardware.master9_controller import Master9Controller
from utils.frame_logger import FrameLogger

logger = logging.getLogger(__name__)

HOST   = "0.0.0.0"
PORT   = 5000
BUFFER = 4096

# Master-9 serial port — adjust if Windows assigns a different COM port
MASTER9_PORT     = "COM3"
MASTER9_BAUDRATE = 9600

# Default LED cycle matching the current Master-9 paradigm
# CH6=Green (10Hz), CH7=Blue (10Hz), CH5=OFF
DEFAULT_LED_CYCLE = ["Green", "Blue"]


class CameraListener:

    def __init__(self):
        self._server_sock  = None
        self._running      = False
        self._m9           = None
        self._m9_lock      = threading.Lock()
        self._frame_logger = None

        signal.signal(signal.SIGINT,  self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # ------------------------------------------------------------------
    # Master-9 helpers
    # ------------------------------------------------------------------

    def _m9_connect(self):
        """Connect to Master-9 via serial. Returns controller or False."""
        m9 = Master9Controller(port=MASTER9_PORT, baudrate=MASTER9_BAUDRATE)
        if m9.connect():
            return m9
        return False

    def _m9_start(self, m9) -> float:
        """
        Fire CH1 master trigger. Returns Unix timestamp of fire moment.
        The routing matrix cascades CH1 → CH3/CH6/CH7 automatically.
        """
        m9.start_sequence()
        fire_time = time.time()
        logger.info(f"Master-9 acquisition STARTED (t={fire_time:.6f})")
        return fire_time

    def _m9_stop(self, m9) -> bool:
        """Stop all Master-9 outputs."""
        return m9.stop()

    def _m9_disconnect(self, m9):
        """Disconnect from Master-9."""
        m9.disconnect()

    # ------------------------------------------------------------------
    # Payload parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_start_payload(payload: str):
        """
        Parse the START command payload.

        Format:  "<func_dir>|<bids_stem>|<led_cycle>"
        led_cycle is optional — omitting it falls back to ["Green", "Blue"].

        Returns
        -------
        (func_dir, bids_stem, led_cycle)
        """
        parts = payload.split("|")

        func_dir  = parts[0].strip() if len(parts) > 0 else "C:/Data/unknown_session"
        bids_stem = parts[1].strip() if len(parts) > 1 else "unknown_"

        if len(parts) > 2 and parts[2].strip():
            led_cycle = [ch.strip() for ch in parts[2].split(",") if ch.strip()]
        else:
            led_cycle = DEFAULT_LED_CYCLE

        return func_dir, bids_stem, led_cycle

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------

    def start(self):
        self._running     = True
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((HOST, PORT))
        self._server_sock.listen(5)

        logger.info("=" * 60)
        logger.info(f"Camera listener ready on port {PORT}")
        logger.info(f"Master-9 serial port: {MASTER9_PORT}")
        logger.info("CH1→master | CH3→camera 20Hz | CH6→Green 10Hz | CH7→Blue 10Hz")
        logger.info("NOTE: Bonsai must be running manually before sending START")
        logger.info("Waiting for commands from PC2...")
        logger.info("=" * 60)

        try:
            while self._running:
                try:
                    self._server_sock.settimeout(1.0)
                    conn, addr = self._server_sock.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(conn, addr),
                        daemon=True
                    ).start()
                except socket.timeout:
                    continue
        finally:
            self._cleanup()

    def _handle_client(self, conn: socket.socket, addr):
        logger.info(f"Connection from {addr}")
        try:
            with conn:
                raw     = conn.recv(BUFFER).decode("utf-8").strip()
                parts   = raw.split(" ", 1)
                command = parts[0].upper()
                payload = parts[1].strip() if len(parts) > 1 else ""

                logger.info(f"Command: {command!r}  Payload: {payload!r}")

                # ---- PING -----------------------------------------------
                if command == "PING":
                    conn.sendall(b"PONG\n")

                # ---- TIMESYNC -------------------------------------------
                elif command == "TIMESYNC":
                    # PC2 sends: "TIMESYNC" (no payload)
                    # PC1 responds: "TIMESYNC <pc1_unix> <pc1_timeofday>"
                    #   pc1_unix      : time.time() at moment of response, 6 d.p.
                    #   pc1_timeofday : local time string "HH:MM:SS.fffffff"
                    #                   (7 decimal places, matches Bonsai CsvWriter format)
                    # PC2 uses pc1_unix + NTP half-RTT to estimate clock offset.
                    import datetime as _dt
                    pc1_time    = time.time()
                    pc1_tod_str = _dt.datetime.now().strftime("%H:%M:%S.%f") + "0"  # pad to 7 dp
                    conn.sendall(
                        f"TIMESYNC {pc1_time:.6f} {pc1_tod_str}\n".encode("utf-8")
                    )
                    logger.debug(f"TIMESYNC: pc1_unix={pc1_time:.6f} tod={pc1_tod_str}")

                # ---- START ----------------------------------------------
                elif command == "START":
                    func_dir, bids_stem, led_cycle = self._parse_start_payload(payload)

                    logger.info(
                        f"START request — LED cycle: {' → '.join(led_cycle)}\n"
                        f"  func dir : {func_dir}\n"
                        f"  BIDS stem: {bids_stem}"
                    )

                    with self._m9_lock:
                        # Stop any already-running session cleanly
                        if self._m9 is not None:
                            logger.warning("START while running — stopping previous session first")
                            if self._frame_logger:
                                self._frame_logger.stop()
                                self._frame_logger = None
                            self._m9_stop(self._m9)
                            self._m9_disconnect(self._m9)
                            self._m9 = None

                        # 1. Connect Master-9
                        m9 = self._m9_connect()
                        if not m9:
                            conn.sendall(b"ERROR\n")
                            return

                        # 2. Fire CH1 master trigger
                        try:
                            fire_time = self._m9_start(m9)
                        except Exception as e:
                            logger.error(f"Master-9 start failed: {e}")
                            self._m9_disconnect(m9)
                            conn.sendall(b"ERROR\n")
                            return

                        self._m9 = m9

                        # 3. Start FrameLogger using fire_time as t=0
                        try:
                            os.makedirs(func_dir, exist_ok=True)
                            self._frame_logger = FrameLogger(
                                func_dir  = func_dir,
                                bids_stem = bids_stem,
                                led_cycle = led_cycle,
                            )
                            self._frame_logger.start(session_start_time=fire_time)
                        except Exception as e:
                            logger.error(f"FrameLogger start failed: {e}")
                            self._frame_logger = None

                        # Send fire_time back to PC2 for session clock alignment
                        conn.sendall(f"OK {fire_time:.6f}\n".encode("utf-8"))
                        logger.info(f"Session started — t0={fire_time:.6f}")

                # ---- STOP -----------------------------------------------
                elif command == "STOP":
                    with self._m9_lock:
                        if self._frame_logger:
                            self._frame_logger.stop()
                            self._frame_logger = None
                        if self._m9 is not None:
                            ok = self._m9_stop(self._m9)
                            self._m9_disconnect(self._m9)
                            self._m9 = None
                        else:
                            ok = True
                            logger.warning("STOP received but Master-9 not running")
                    conn.sendall(b"OK\n" if ok else b"ERROR\n")

                # ---- EXIT -----------------------------------------------
                elif command == "EXIT":
                    with self._m9_lock:
                        if self._frame_logger:
                            self._frame_logger.stop()
                            self._frame_logger = None
                        if self._m9 is not None:
                            self._m9_stop(self._m9)
                            self._m9_disconnect(self._m9)
                            self._m9 = None
                    conn.sendall(b"OK\n")
                    logger.info("EXIT — shutting down listener")
                    self._running = False

                else:
                    logger.warning(f"Unknown command: {command!r}")
                    conn.sendall(b"UNKNOWN\n")

        except Exception as e:
            logger.error(f"Client handler error: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _cleanup(self):
        logger.info("Cleaning up...")
        with self._m9_lock:
            if self._frame_logger:
                self._frame_logger.stop()
                self._frame_logger = None
            if self._m9 is not None:
                self._m9_stop(self._m9)
                self._m9_disconnect(self._m9)
                self._m9 = None
        if self._server_sock:
            self._server_sock.close()
        logger.info("Camera listener stopped cleanly")

    def _signal_handler(self, sig, frame):
        logger.info(f"Signal {sig} — shutting down")
        self._running = False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("camera_listener.log", encoding="utf-8")
        ]
    )
    listener = CameraListener()
    listener.start()
