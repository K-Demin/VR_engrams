# -*- coding: utf-8 -*-
"""
Created on Wed Mar 11 13:51:09 2026

@author: NeuRLab
"""

# test_pipeline.py
#
# Run this on PC2 to verify the full pipeline:
#   PC2 → TCP → PC1 → Master-9 → Camera + LEDs
#
# Run BEFORE main_pipeline.py to confirm everything is working.
# camera_listener.py must already be running on PC1.
#
# Usage:
#   python test_pipeline.py

import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

sys.path.insert(0, ".")
from utils.camera_control import ping_camera, start_camera, stop_camera, exit_listener


def run_tests():
    print()
    print("=" * 55)
    print("  Widefield Pipeline Integration Test")
    print("=" * 55)
    print()

    # ----------------------------------------------------------
    # Test 1: TCP connectivity
    # ----------------------------------------------------------
    print("Test 1: TCP connectivity (PING)")
    ok = ping_camera()
    if not ok:
        print("  ✗ FAILED — PC1 not reachable")
        print("  → Check camera_listener.py is running on PC1")
        print("  → Check PC1 IP in camera_control.py")
        print("  → Check Windows Firewall on PC1 (port 5000)")
        sys.exit(1)
    print("  ✓ PASSED — PC1 online\n")

    # ----------------------------------------------------------
    # Test 2: START command
    # ----------------------------------------------------------
    print("Test 2: START acquisition")
    print("  → Watch scope: CH3 should pulse at 33.3Hz")
    print("                 CH6 Green 25ms ON every 90ms at t=0")
    print("                 CH5 Red   25ms ON every 90ms at t=30ms")
    print("                 CH7 Blue  25ms ON every 90ms at t=60ms")
    ok = start_camera()
    if not ok:
        print("  ✗ FAILED — START command rejected by PC1")
        sys.exit(1)
    print("  ✓ Command accepted\n")

    # Let it run for 5 seconds so you can verify on scope/Solis
    print("  Running for 5 seconds — verify signals now...")
    for i in range(5, 0, -1):
        print(f"  Stopping in {i}s...", end="\r")
        time.sleep(1)
    print()

    # ----------------------------------------------------------
    # Test 3: STOP command
    # ----------------------------------------------------------
    print("Test 3: STOP acquisition")
    print("  → Scope should go flat immediately")
    ok = stop_camera()
    if not ok:
        print("  ✗ FAILED — STOP command rejected by PC1")
        sys.exit(1)
    print("  ✓ Command accepted\n")
    time.sleep(1)

    # ----------------------------------------------------------
    # Test 4: Repeated start/stop cycles
    # ----------------------------------------------------------
    print("Test 4: Reliability — 5 start/stop cycles")
    for i in range(1, 6):
        ok_start = start_camera()
        time.sleep(0.5)
        ok_stop = stop_camera()
        time.sleep(0.5)
        status = "✓" if (ok_start and ok_stop) else "✗"
        print(f"  {status} Cycle {i}: start={ok_start} stop={ok_stop}")
        if not (ok_start and ok_stop):
            print("  ✗ FAILED — reliability test failed")
            sys.exit(1)
    print("  ✓ All cycles passed\n")

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("=" * 55)
    print("  All tests passed — pipeline ready")
    print("=" * 55)
    print()
    print("Next steps:")
    print("  1. Confirm Solis is acquiring frames during START")
    print("  2. Check frame rate in Solis matches 33.3 Hz")
    print("  3. Run main_pipeline.py for a full behavioural session")
    print()


if __name__ == "__main__":
    run_tests()