# -*- coding: utf-8 -*-
"""
hardware/master9_controller.py

Controls the AMPI Master-9 pulse generator via RS-232 serial.

Paradigm structure (pre-programmed in Master-9 GUI, paradigm 1):
    CH1 → master trigger  — Python fires this only. The routing matrix
                            cascades CH1 to all slave channels below.
    CH3 → Andor Solis camera trigger (slaved to CH1)
              D=40ms, I=50ms, N=7200  →  20 Hz
    CH6 → Green LED (slaved to CH1)
              D=20ms, I=100ms, N=3600  →  10 Hz
    CH7 → Blue LED (slaved to CH1)
              D=45ms, I=100ms, N=3600  →  10 Hz
    CH5 → OFF (Red LED not used in current paradigm)

Python's only job:
    start:  TRIG 1   — fires CH1; hardware handles all timing and phase
    stop:   STOP     — stops all outputs immediately

Timing and phase relationships are entirely defined in the stored
Master-9 paradigm. Python never touches slave channels directly —
doing so bypasses the routing matrix and breaks phase alignment.
"""

import serial
import time
import logging

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Channel map — must match Master-9 GUI paradigm
# ------------------------------------------------------------------
CH_MASTER         = 1   # CH1 → master trigger (cascades via routing matrix)
CH_CAMERA_TRIGGER = 3   # CH3 → Andor Solis, 20 Hz (slaved to CH1)
CH_GREEN_LED      = 6   # CH6 → Green LED, 10 Hz (slaved to CH1)
CH_BLUE_LED       = 7   # CH7 → Blue LED, 10 Hz (slaved to CH1)
# CH5 (Red LED) is OFF in current paradigm — never referenced


class Master9Controller:
    """
    Controls AMPI Master-9 via RS-232 serial.

    Usage
    -----
        m9 = Master9Controller(port="COM3")
        m9.connect()
        m9.start_sequence()   # fires CH1; paradigm routing does the rest
        ...
        m9.stop()
        m9.disconnect()
    """

    def __init__(self, port: str = "COM3", baudrate: int = 9600):
        self._port      = port
        self._baudrate  = baudrate
        self._ser       = None
        self._connected = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Open serial port and send a STOP to ensure outputs are idle.
        Blocks for ~2s while the Master-9 initialises after port open.
        """
        try:
            self._ser = serial.Serial(
                self._port,
                self._baudrate,
                timeout=1
            )
            time.sleep(2.0)   # Master-9 needs ~2s after serial open
            self._connected = True
            logger.info(f"Master-9 connected on {self._port} at {self._baudrate} baud")

            # Ensure everything is stopped on connect
            self._send("STOP")
            time.sleep(0.1)
            return True

        except serial.SerialException as e:
            logger.error(f"Master-9 serial connect failed on {self._port}: {e}")
            return False

    def disconnect(self) -> None:
        """
        Send STOP then close the serial port.
        Always call this before opening the Master-9 GUI.
        """
        if self._ser and self._ser.is_open:
            try:
                self._send("STOP")
                time.sleep(0.05)
                self._ser.close()
                logger.info("Master-9 disconnected")
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._connected = False

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def start_sequence(self) -> bool:
        """
        Fire CH1 (master trigger).

        The Master-9 routing matrix cascades this to:
            CH3 → camera trigger  (20 Hz, D=40ms)
            CH6 → Green LED       (10 Hz, D=20ms)
            CH7 → Blue LED        (10 Hz, D=45ms)

        Phase relationships are guaranteed by the hardware paradigm.
        Never call TRIG on slave channels directly.
        """
        if not self._connected:
            logger.error("Cannot start: Master-9 not connected")
            return False
        try:
            self._send(f"TRIG {CH_MASTER}")
            logger.info(
                "Master-9 started — CH1 fired via routing matrix:\n"
                f"  CH{CH_CAMERA_TRIGGER} camera trigger → 20 Hz\n"
                f"  CH{CH_GREEN_LED} Green LED        → 10 Hz\n"
                f"  CH{CH_BLUE_LED} Blue LED         → 10 Hz"
            )
            return True
        except Exception as e:
            logger.error(f"start_sequence() failed: {e}")
            return False

    def stop(self) -> bool:
        """
        Stop all Master-9 outputs immediately.
        Safe to call from signal handlers or exception blocks.
        """
        if not self._connected:
            logger.warning("stop() called but Master-9 is not connected")
            return False
        try:
            self._send("STOP")
            logger.info("Master-9 stopped — all outputs OFF")
            return True
        except Exception as e:
            logger.error(f"stop() failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, command: str):
        """Send a single ASCII command terminated with carriage return."""
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Serial port is not open")
        self._ser.write((command + "\r").encode())
        logger.debug(f"Master-9 ← {command!r}")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ser is not None and self._ser.is_open
