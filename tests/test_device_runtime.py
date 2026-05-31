from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SRC_ROOT))

from vr_engrams.bids import BIDSPath
from vr_engrams.camera_sync import CameraSyncClient
from vr_engrams.cli import _reward_duration_sec
from vr_engrams.config_v2 import ConfigValidationError, load_experiment_v2_config, validate_experiment_v2_config
from vr_engrams.lick_detector import LickDetector
from vr_engrams.logger import ExperimentLogger


class FakeCameraClient(CameraSyncClient):
    def __init__(self, responses: list[tuple[str, float, float]]) -> None:
        super().__init__(host="127.0.0.1", port=5000)
        self.responses = responses
        self.commands: list[str] = []

    def _send_command(self, command: str, timeout: float) -> tuple[str, float, float]:
        self.commands.append(command)
        return self.responses.pop(0)


class DeviceRuntimeTests(unittest.TestCase):
    def test_analog_lick_low_is_lick(self) -> None:
        detector = object.__new__(LickDetector)
        detector.logic_mode = "low_is_lick"
        detector.threshold = 1.0

        self.assertTrue(detector._sensor_active(0.2))
        self.assertTrue(detector._sensor_active(1.0))
        self.assertFalse(detector._sensor_active(1.2))

    def test_analog_lick_high_is_lick(self) -> None:
        detector = object.__new__(LickDetector)
        detector.logic_mode = "high_is_lick"
        detector.threshold = 2.5

        self.assertFalse(detector._sensor_active(2.4))
        self.assertTrue(detector._sensor_active(2.5))
        self.assertTrue(detector._sensor_active(4.0))

    def test_reward_duration_ms_converts_to_seconds(self) -> None:
        config = {"stimuli": {"reward_valve": {"duration_ms": 50}}}
        self.assertAlmostEqual(_reward_duration_sec(config), 0.05)

    def test_camera_clock_and_start_parsing(self) -> None:
        client = FakeCameraClient(
            [
                ("TIMESYNC 105.010 12:00:00.0000000", 100.000, 100.020),
                ("TIMESYNC 106.020 12:00:01.0000000", 101.000, 101.040),
                ("TIMESYNC 107.030 12:00:02.0000000", 102.000, 102.060),
                ("OK 123.456", 200.000, 200.010),
            ]
        )

        clock_sync = client.measure_clock_offset(n_samples=3)
        ok, start_time = client.start("C:/data/sub-M001/ses-1/func", bids_stem="sub-M001_", led_cycle=["Green", "Blue"])

        self.assertAlmostEqual(clock_sync["pc1_minus_pc2_seconds"], 5.0)
        self.assertEqual(clock_sync["n_samples"], 3)
        self.assertTrue(ok)
        self.assertEqual(start_time, 123.456)
        self.assertEqual(client.commands[-1], "START C:/data/sub-M001/ses-1/func|sub-M001_|Green,Blue")

    def test_camera_start_rejects_malformed_response(self) -> None:
        client = FakeCameraClient([("NOT_OK", 1.0, 1.1)])
        with self.assertRaises(ValueError):
            client.start("C:/data")

    def test_bids_path_builder(self) -> None:
        path = BIDSPath(
            project_root_pc2=Path("data"),
            project_root_pc1="C:/pc1/data",
            sub="sub-M001",
            ses="ses-1",
            task="task-vrengrams",
            run="run-2",
        )

        self.assertEqual(path.func_dir_pc2, Path("data/sub-M001/ses-1/func"))
        self.assertEqual(path.func_dir_pc1, "C:/pc1/data/sub-M001/ses-1/func")
        self.assertEqual(path.filename("events"), "sub-M001_ses-1_task-vrengrams_run-2_events")

    def test_logger_events_tsv_uses_pc1_t0(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bids_path = BIDSPath(
                project_root_pc2=Path(tmp),
                project_root_pc1="C:/pc1/data",
                sub="M001",
                ses=1,
                task="vrengrams",
                run=1,
            )
            logger = ExperimentLogger(
                root_dir=Path(tmp) / "legacy",
                animal_id="M001",
                config={"session": {"task_label": "vrengrams"}},
                bids_path=bids_path,
                console_echo=False,
            )
            with patch("vr_engrams.logger.time.time", return_value=1002.5):
                logger.start_session(session_start_unix=1000.0)
                logger.log_event("stimulus_on", trial=4, duration_sec=0.25, phase="decoder")
            logger.close()

            lines = bids_path.events_tsv_pc2.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "onset\tduration\ttrial_type\ttrial\tdetail")
            self.assertIn("2.500000\t0.25\tstimulus_on\t4\t", lines[-1])

    def test_logger_applies_pc1_pc2_clock_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bids_path = BIDSPath(
                project_root_pc2=Path(tmp),
                project_root_pc1="C:/pc1/data",
                sub="M001",
                ses=1,
                task="vrengrams",
                run=1,
            )
            logger = ExperimentLogger(
                root_dir=Path(tmp) / "legacy",
                animal_id="M001",
                config={"session": {"task_label": "vrengrams"}},
                bids_path=bids_path,
                console_echo=False,
            )
            logger.update_clock_sync({"pc1_minus_pc2_seconds": 0.25})
            with patch("vr_engrams.logger.time.time", return_value=1002.5):
                logger.start_session(session_start_unix=1000.0)
                logger.log_event("stimulus_on", duration_sec=0.25)
            logger.close()

            lines = bids_path.events_tsv_pc2.read_text(encoding="utf-8").splitlines()
            self.assertIn("2.750000\t0.25\tstimulus_on\t", lines[-1])

    def test_shipped_v2_configs_validate(self) -> None:
        for config_name in ["experiment_v2.yaml", "decoder_only.yaml", "fmri_opto.yaml"]:
            with self.subTest(config_name=config_name):
                config = load_experiment_v2_config(REPO_ROOT / "configs" / config_name)
                self.assertIn("session", config)

    def test_config_validation_rejects_missing_lick_channel(self) -> None:
        config = _minimal_valid_config()
        config["channels"]["analog_inputs"] = {}

        with self.assertRaises(ConfigValidationError) as caught:
            validate_experiment_v2_config(config)
        self.assertIn("Configured lick input 'lick'", str(caught.exception))

    def test_config_validation_rejects_missing_imaging_session_fields(self) -> None:
        config = _minimal_valid_config()
        del config["session"]["session_num"]

        with self.assertRaises(ConfigValidationError) as caught:
            validate_experiment_v2_config(config)
        self.assertIn("session.session_num", str(caught.exception))


def _minimal_valid_config() -> dict:
    return {
        "daq": {"enabled": False, "opto_mode": "arduino"},
        "channels": {
            "digital_outputs": {"opto": "Dev1/port1/line0", "ir_led": "Dev1/port0/line1"},
            "digital_inputs": {},
            "analog_outputs": {"reward_valve": "Dev1/ao1"},
            "analog_inputs": {"lick": "Dev1/ai2"},
        },
        "stimuli": {
            "audio": {},
            "visual": {},
            "whisker": {"output_name": "puff"},
            "shock": {"output_name": "shock"},
            "opto": {"output_name": "opto"},
            "reward_valve": {"output_name": "reward_valve", "duration_ms": 50},
        },
        "phases": {},
        "randomization": {},
        "logging": {"output_root": "./data"},
        "session": {
            "name": "test",
            "task_label": "test",
            "session_num": 1,
            "run_num": 1,
            "lick_input_name": "lick",
            "reward_output_name": "reward_valve",
            "lick_logic_mode": "low_is_lick",
        },
        "imaging": {
            "enabled": True,
            "pc1_host": "127.0.0.1",
            "pc1_port": 5000,
            "led_cycle": ["Green", "Blue"],
            "frame_rate": 20.0,
            "ir_led_output_name": "ir_led",
        },
    }


if __name__ == "__main__":
    unittest.main()
