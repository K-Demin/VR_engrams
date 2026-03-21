# -*- coding: utf-8 -*-
"""
Created on Wed Mar 11 10:15:45 2026

@author: NeuRLab
"""

# utils/camera_control.py
#
# Runs on PC2 (behaviour control computer).
# Sends commands to camera_listener.py running on PC1.
#
# Usage:
#   from utils.camera_control import ping_camera, start_camera, stop_camera

import socket
import logging

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# PC1 network settings
# ------------------------------------------------------------------
PC1_HOST     = "115.145.185.228"
PC1_PORT     = 5000
TIMEOUT_PING = 5.0    # seconds — PING is near-instant
TIMEOUT_CMD  = 15.0   # seconds — START/STOP involve multiple COM calls


def _send_command(command: str, timeout: float = TIMEOUT_CMD) -> str:
    """
    Send a single command to PC1 camera_listener and return the response.
    Each call opens a fresh connection — simple and reliable.
    Raises ConnectionError on socket failure so callers handle it explicitly.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((PC1_HOST, PC1_PORT))
            s.sendall(f"{command}\n".encode("utf-8"))
            response = s.recv(1024).decode("utf-8").strip()
            logger.debug(f"CMD={command!r}  RESP={response!r}")
            return response
    except socket.timeout:
        raise ConnectionError(f"Timeout ({timeout}s) waiting for response to {command!r}")
    except OSError as e:
        raise ConnectionError(f"Socket error sending {command!r}: {e}")


def ping_camera() -> bool:
    """
    Check TCP connectivity to PC1 camera listener.
    Returns True if PC1 responds with PONG.
    """
    try:
        resp = _send_command("PING", timeout=TIMEOUT_PING)
        ok = resp == "PONG"
        if ok:
            logger.info("PC1 camera listener: online (PONG received)")
        else:
            logger.warning(f"Unexpected PING response: {resp!r}")
        return ok
    except ConnectionError as e:
        logger.error(f"ping_camera() failed: {e}")
        return False


def start_camera(session_path: str) -> bool:
    """
    Tell PC1 to start Master-9 acquisition and begin frame logging.

    session_path : shared folder path visible from both PCs, e.g.
                   "Y:/M001/2026-03-11/puff_task_14-00-00"
                   PC1 will write frame_log.csv into this folder.
    """
    try:
        resp = _send_command(f"START {session_path}", timeout=TIMEOUT_CMD)
        ok = resp == "OK"
        if ok:
            logger.info(f"Camera acquisition started — frame log → {session_path}")
        else:
            logger.error(f"START command failed, PC1 response: {resp!r}")
        return ok
    except ConnectionError as e:
        logger.error(f"start_camera() failed: {e}")
        return False


def stop_camera() -> bool:
    """
    Tell PC1 to stop Master-9 acquisition.
    Forces CH3 and CH5/6/7 LOW immediately.
    """
    try:
        resp = _send_command("STOP", timeout=TIMEOUT_CMD)
        ok = resp == "OK"
        if ok:
            logger.info("Camera acquisition stopped (CH3 and CH5/6/7 LOW)")
        else:
            logger.error(f"STOP command failed, PC1 response: {resp!r}")
        return ok
    except ConnectionError as e:
        logger.error(f"stop_camera() failed: {e}")
        return False


def exit_listener() -> bool:
    """
    Tell PC1 to shut down camera_listener cleanly.
    Call once at end of session — requires manual restart of listener on PC1.
    """
    try:
        resp = _send_command("EXIT", timeout=TIMEOUT_CMD)
        ok = resp == "OK"
        if ok:
            logger.info("PC1 camera listener shut down")
        return ok
    except ConnectionError as e:
        logger.error(f"exit_listener() failed: {e}")
        return False