# -*- coding: utf-8 -*-
"""
utils/elp_camera.py

ELP USB behaviour camera controller for PC1.
Controls Bonsai as a subprocess — Bonsai handles acquisition and recording,
Python handles start/stop timing synchronised with Master-9.

Architecture
------------
camera_listener.py receives START <session_path> from PC2
  └─ _m9_start()       → starts Andor imaging via Master-9
  └─ ELPCamera.start() → launches Bonsai with output path as argument
                         Bonsai opens camera, begins recording + preview immediately
camera_listener.py receives STOP from PC2
  └─ _m9_stop()        → stops Andor imaging
  └─ ELPCamera.stop()  → sends Bonsai a clean shutdown signal, waits for file flush

Why subprocess rather than Bonsai TCP node
------------------------------------------
Bonsai's TcpServer node is functional but requires careful workflow design
and is fragile to debug remotely. Subprocess control is simpler, robust,
and is the approach used by most Python-based neuroscience rigs that
integrate Bonsai (e.g. UCL Cortex-Lab, SWC rigs).

Bonsai workflow behaviour
-------------------------
The workflow (bonsai_elp_workflow.bonsai) is designed to:
  - Accept --no-editor flag → runs headless (no Bonsai GUI)
  - Accept --property flags to set output path and camera index at launch
  - Start recording immediately on launch (no GUI interaction needed)
  - Show a preview window (OpenCV Visualizer node inside Bonsai)
  - Flush and close the AVI cleanly when the process receives SIGTERM / is terminated

Bonsai path
-----------
Set BONSAI_EXE in puff_task.yaml under elp_camera.bonsai_exe.
Example: "C:/Users/User/AppData/Local/Bonsai/Bonsai.exe"
Run `where Bonsai` or `where bonsai.exe` in CMD on PC1 to find it.
"""

import subprocess
import threading
import logging
import os
import time
import signal

logger = logging.getLogger(__name__)

# How long to wait for Bonsai to fully start before declaring success (seconds)
BONSAI_START_TIMEOUT = 10.0

# How long to wait for Bonsai to flush video and exit cleanly after stop (seconds)
BONSAI_STOP_TIMEOUT = 15.0


class ELPCamera:
    """
    Non-blocking ELP camera controller via Bonsai subprocess.

    Bonsai is launched with --no-editor so it runs without the GUI.
    The workflow starts recording immediately and shows a preview window.
    On stop(), the process is terminated and Bonsai flushes the AVI to disk.

    Thread-safe: start() and stop() can be called from the camera_listener
    handler thread without blocking the main server loop.
    """

    def __init__(self, config: dict):
        """
        Parameters
        ----------
        config : dict
            The 'elp_camera' section from puff_task.yaml. Expected keys:
              bonsai_exe      : full path to Bonsai.exe
              workflow        : full path to bonsai_elp_workflow.bonsai
              device_index    : USB camera device index (default 0)
              width           : capture width in pixels (default 1280)
              height          : capture height in pixels (default 720)
              fps             : capture frame rate (default 30)
              enabled         : bool — set False to skip ELP entirely (default True)
        """
        self._bonsai_exe   = config.get("bonsai_exe",   "C:/Users/User/AppData/Local/Bonsai/Bonsai.exe")
        self._workflow     = config.get("workflow",      "C:/behaviour_pipeline/utils/bonsai_elp_workflow.bonsai")
        self._device_index = config.get("device_index", 0)
        self._width        = config.get("width",        1280)
        self._height       = config.get("height",        720)
        self._fps          = config.get("fps",            30)
        self._enabled      = config.get("enabled",       True)

        self._process      = None
        self._lock         = threading.Lock()
        self._monitor_thread = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, session_path: str) -> bool:
        """
        Launch Bonsai and begin recording to session_path/body_camera.avi.

        Returns True if Bonsai launched successfully, False otherwise.
        A return value of True means the process started — not that the
        first frame has been captured. Allow ~1s for the camera to open.
        """
        if not self._enabled:
            logger.info("ELPCamera disabled in config — skipping")
            return True

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                logger.warning("ELPCamera.start() called while Bonsai is already running")
                return True

            # Validate paths before launching
            if not os.path.isfile(self._bonsai_exe):
                logger.error(
                    f"Bonsai executable not found: {self._bonsai_exe}\n"
                    f"Set elp_camera.bonsai_exe in puff_task.yaml"
                )
                return False

            if not os.path.isfile(self._workflow):
                logger.error(
                    f"Bonsai workflow not found: {self._workflow}\n"
                    f"Set elp_camera.workflow in puff_task.yaml"
                )
                return False

            output_file = os.path.join(session_path, "body_camera.avi").replace("/", "\\")

            # Build Bonsai command
            # --no-editor     : run headless (no Bonsai GUI window)
            # --start         : begin workflow execution immediately
            # --property      : override workflow properties at launch
            #                   FilePath      → output AVI path
            #                   DeviceIndex   → USB camera index
            #                   FrameWidth    → capture width
            #                   FrameHeight   → capture height
            #                   FrameRate     → capture FPS
            cmd = [
                self._bonsai_exe,
                self._workflow,
                "--no-editor",
                "--start",
                f"--property:FileCapture.FileName={output_file}",
                f"--property:VideoCapture.Index={self._device_index}",
                f"--property:VideoCapture.CaptureProperties[FrameWidth]={self._width}",
                f"--property:VideoCapture.CaptureProperties[FrameHeight]={self._height}",
                f"--property:VideoCapture.CaptureProperties[Fps]={self._fps}",
            ]

            logger.info(f"Launching Bonsai ELP workflow → {output_file}")
            logger.debug(f"Command: {' '.join(cmd)}")

            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP  # Windows: allows clean CTRL+BREAK
                )
            except FileNotFoundError:
                logger.error(f"Could not launch Bonsai — check path: {self._bonsai_exe}")
                return False
            except Exception as e:
                logger.error(f"Failed to launch Bonsai: {e}")
                return False

        # Wait briefly and check Bonsai didn't immediately crash
        time.sleep(2.0)  # Bonsai takes ~1-2s to open camera and start workflow
        with self._lock:
            if self._process.poll() is not None:
                # Process already exited — something went wrong
                stdout, stderr = self._process.communicate()
                logger.error(
                    f"Bonsai exited immediately (code {self._process.returncode})\n"
                    f"stdout: {stdout.decode('utf-8', errors='replace')}\n"
                    f"stderr: {stderr.decode('utf-8', errors='replace')}"
                )
                self._process = None
                return False

        logger.info(f"Bonsai ELP camera running (PID {self._process.pid})")

        # Monitor thread — logs if Bonsai crashes unexpectedly during experiment
        self._monitor_thread = threading.Thread(
            target=self._monitor_process,
            daemon=True,
            name="ELPMonitor"
        )
        self._monitor_thread.start()

        return True

    def stop(self) -> bool:
        """
        Stop Bonsai recording and wait for AVI to be flushed to disk.

        Sends CTRL+BREAK (Windows) to allow Bonsai to finalise the video
        file cleanly. Falls back to terminate() if Bonsai doesn't exit
        within BONSAI_STOP_TIMEOUT seconds.

        Returns True if stopped cleanly, False if forcibly killed.
        """
        if not self._enabled:
            return True

        with self._lock:
            if self._process is None or self._process.poll() is not None:
                logger.info("ELPCamera.stop(): Bonsai not running — nothing to stop")
                self._process = None
                return True
            proc = self._process

        logger.info("Stopping Bonsai ELP recording...")

        # Send CTRL+BREAK — Bonsai handles this as a clean shutdown signal on Windows
        # This allows Bonsai to flush buffers and close the AVI properly
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception as e:
            logger.warning(f"CTRL+BREAK failed ({e}) — trying terminate()")
            proc.terminate()

        # Wait for clean exit
        clean_exit = False
        try:
            proc.wait(timeout=BONSAI_STOP_TIMEOUT)
            clean_exit = True
            logger.info(f"Bonsai exited cleanly (code {proc.returncode})")
        except subprocess.TimeoutExpired:
            logger.warning(
                f"Bonsai did not exit within {BONSAI_STOP_TIMEOUT}s — forcing kill. "
                f"The AVI may be incomplete. Check body_camera.avi file size."
            )
            proc.kill()
            proc.wait()

        with self._lock:
            self._process = None

        return clean_exit

    @property
    def is_running(self) -> bool:
        """True if Bonsai process is alive."""
        with self._lock:
            return self._process is not None and self._process.poll() is None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _monitor_process(self):
        """
        Background thread — waits for Bonsai to exit and logs the outcome.
        This catches unexpected crashes during recording.
        """
        proc = self._process
        if proc is None:
            return
        proc.wait()  # blocks until Bonsai exits for any reason

        with self._lock:
            # Only log as error if we didn't intentionally stop it
            if self._process is not None:
                logger.error(
                    f"Bonsai ELP process exited unexpectedly "
                    f"(code {proc.returncode}) — body camera recording may be incomplete"
                )
                self._process = None
