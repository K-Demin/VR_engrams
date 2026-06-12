from __future__ import annotations

import sys
import tempfile
import unittest
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SRC_ROOT))

from vr_engrams.bids import BIDSPath
from vr_engrams.camera_sync import CameraSyncClient
from vr_engrams.cli import _reward_duration_sec, _run_background_period
from vr_engrams.config_v2 import ConfigValidationError, load_experiment_v2_config, validate_experiment_v2_config
from vr_engrams.lick_detector import LickDetector
from vr_engrams.logger import ExperimentLogger
from vr_engrams.phases.protocol_phases import DecoderTrainingPhase, PreConditioningScenePhase, _deliver_puff_train
from vr_engrams.stimulus_controller import StimulusController
from vr_engrams.visual_engine import VisualEngine


class FakeCameraClient(CameraSyncClient):
    def __init__(self, responses: list[tuple[str, float, float]]) -> None:
        super().__init__(host="127.0.0.1", port=5000)
        self.responses = responses
        self.commands: list[str] = []

    def _send_command(self, command: str, timeout: float) -> tuple[str, float, float]:
        self.commands.append(command)
        return self.responses.pop(0)


class FakeDaqForPuff:
    enabled = True
    do_tasks = {}
    opto_counter_channel = None
    allow_software_fallback = False
    opto_freq_hz = 20.0
    opto_pulse_width_s = 0.015
    opto_arduino_port = "COM3"
    opto_arduino_pin = 9
    opto_arduino_active_low = False
    opto_arduino_reset_on_connect = False
    opto_arduino_startup_wait_s = 0.05

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def write_output(self, name: str, state: bool) -> None:
        self.calls.append(("write_output", name, state))

    def trigger_puff(self, channel: str, duration_sec: float) -> str:
        self.calls.append(("trigger_puff", channel, duration_sec))
        return "fake_puff"


class FakeLoggerForPuff:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event: str, **fields) -> None:
        self.events.append((event, fields))


class FakeAudioEngine:
    enabled = True
    init_error = None
    active_backend = "fake_audio"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def play_tone(
        self,
        frequency_hz: float,
        duration_sec: float,
        side: str = "both",
        volume: float = 0.25,
        block: bool = True,
    ) -> str:
        self.calls.append(
            {
                "frequency_hz": frequency_hz,
                "duration_sec": duration_sec,
                "side": side,
                "volume": volume,
                "block": block,
            }
        )
        return "fake_audio"


class FakeDotStim:
    def draw(self) -> None:
        return None


class FakeVisualModule:
    def __init__(self) -> None:
        self.dot_kwargs: dict | None = None

    def DotStim(self, window, **kwargs) -> FakeDotStim:
        self.dot_kwargs = kwargs
        return FakeDotStim()


class FakeWindow:
    size = [1920, 1080]
    color = [-1, -1, -1]

    def flip(self) -> None:
        return None


class FakeBackgroundVisual:
    def __init__(self) -> None:
        self.black_calls = 0

    def show_black(self) -> None:
        self.black_calls += 1


class FakeBackgroundAudio:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


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

    def test_background_period_logs_timing_and_holds_black(self) -> None:
        logger = FakeLoggerForPuff()
        visual = FakeBackgroundVisual()
        audio = FakeBackgroundAudio()
        stimuli = SimpleNamespace(visual_engine=visual, audio_engine=audio)

        with patch("vr_engrams.cli.time.sleep") as sleep_mock, patch("vr_engrams.cli.time.perf_counter", side_effect=[10.0, 40.1]):
            _run_background_period(
                config={"background": {"enabled": True, "duration_sec": 30.0}},
                stimuli=stimuli,  # type: ignore[arg-type]
                logger=logger,  # type: ignore[arg-type]
            )

        self.assertEqual(audio.stop_calls, 1)
        self.assertEqual(visual.black_calls, 2)
        sleep_mock.assert_called_once_with(30.0)
        self.assertEqual(logger.events[0][0], "background_start")
        self.assertEqual(logger.events[0][1]["duration_sec"], 30.0)
        self.assertFalse(logger.events[0][1]["reward_available"])
        self.assertFalse(logger.events[0][1]["lick_monitor_active"])
        self.assertEqual(logger.events[1][0], "background_end")
        self.assertAlmostEqual(logger.events[1][1]["actual_duration_sec"], 30.1)

    def test_lick_reward_has_separate_refractory(self) -> None:
        detector = object.__new__(LickDetector)
        detector._reward_on_lick = True
        detector._last_reward_time = float("-inf")
        detector.reward_refractory_sec = 1.0
        detector.reward_delay_sec = 0.0
        rewards: list[str] = []
        detector.reward_callback = lambda: rewards.append("reward")
        detector.logger = FakeLoggerForPuff()

        self.assertTrue(detector._trigger_reward_if_allowed(10.0))
        self.assertFalse(detector._trigger_reward_if_allowed(10.5))
        self.assertTrue(detector._trigger_reward_if_allowed(11.1))

        self.assertEqual(rewards, ["reward", "reward"])

    def test_decoder_maps_puff_b_to_selector_plus_main_valve(self) -> None:
        context = SimpleNamespace(rng=random.Random(1))
        phase = DecoderTrainingPhase(
            context=context,
            config={
                "conditions": ["whisker_a", "whisker_b"],
                "reps_per_condition": 1,
                "event_duration_sec": [2.0, 2.0],
                "iti_sec": [1.0, 1.0],
                "_stimuli": {
                    "whisker": {
                        "output_name": "puff",
                        "side_selector_output_name": "puff_b_selector",
                        "puff_a_selector_state": False,
                        "puff_b_selector_state": True,
                        "selector_reset_state": False,
                        "duration_sec": 0.05,
                        "puff_b_duration_sec": 0.06,
                        "puff_a_frequency_hz": 1.0,
                        "puff_b_frequency_hz": 2.0,
                    }
                },
            },
        )

        trials = {trial["condition"]: trial for trial in phase._build_trials()}
        self.assertEqual(trials["whisker_a"]["puff_channel"], "puff")
        self.assertEqual(trials["whisker_b"]["puff_channel"], "puff")
        self.assertEqual(trials["whisker_b"]["puff_selector_channel"], "puff_b_selector")
        self.assertTrue(trials["whisker_b"]["puff_selector_state"])
        self.assertFalse(trials["whisker_b"]["puff_selector_reset_state"])
        self.assertEqual(trials["whisker_b"]["puff_duration_sec"], 0.06)
        self.assertEqual(trials["whisker_a"]["puff_frequency_hz"], 1.0)
        self.assertEqual(trials["whisker_b"]["puff_frequency_hz"], 2.0)

    def test_decoder_sound_uses_event_window_duration(self) -> None:
        context = SimpleNamespace(rng=random.Random(1))
        phase = DecoderTrainingPhase(
            context=context,
            config={
                "conditions": ["sound_a", "sound_b"],
                "reps_per_condition": 1,
                "event_duration_sec": [2.0, 2.0],
                "iti_sec": [1.0, 1.0],
                "_stimuli": {
                    "audio": {
                        "cue_duration_sec": 0.5,
                        "sound_a_frequency_hz": 8000.0,
                        "sound_b_frequency_hz": 12000.0,
                    }
                },
            },
        )

        trials = {trial["condition"]: trial for trial in phase._build_trials()}

        self.assertEqual(trials["sound_a"]["duration_sec"], 2.0)
        self.assertNotIn("sound_duration_sec", trials["sound_a"])
        self.assertNotIn("sound_duration_sec", trials["sound_b"])

    def test_stimulus_controller_sound_blocks_by_default(self) -> None:
        daq = FakeDaqForPuff()
        logger = FakeLoggerForPuff()
        audio = FakeAudioEngine()
        controller = StimulusController(daq=daq, logger=logger, audio_engine=audio)

        controller.deliver_sound(frequency_hz=8000.0, duration_sec=0.5, side="both")

        self.assertEqual(audio.calls[-1]["duration_sec"], 0.5)
        self.assertTrue(audio.calls[-1]["block"])

    def test_screen_b_dotstim_uses_stable_reference_parameters(self) -> None:
        fake_visual = FakeVisualModule()
        engine = object.__new__(VisualEngine)
        engine.enabled = True
        engine._visual = fake_visual
        engine._windows = [FakeWindow()]

        self.assertTrue(engine.present("screen_b", duration_sec=0.0))

        self.assertIsNotNone(fake_visual.dot_kwargs)
        self.assertEqual(fake_visual.dot_kwargs["fieldSize"], 1920.0)
        self.assertEqual(fake_visual.dot_kwargs["signalDots"], "same")
        self.assertEqual(fake_visual.dot_kwargs["dotLife"], 1000)
        self.assertEqual(fake_visual.dot_kwargs["dir"], 0)

    def test_stimulus_controller_puff_b_sequence(self) -> None:
        daq = FakeDaqForPuff()
        logger = FakeLoggerForPuff()
        controller = StimulusController(daq=daq, logger=logger)

        controller.deliver_puff(
            channel="puff",
            duration_sec=0.05,
            selector_channel="puff_b_selector",
            selector_state=True,
            selector_settle_sec=0.0,
            reset_selector_state=False,
        )

        self.assertEqual(
            daq.calls,
            [
                ("write_output", "puff_b_selector", True),
                ("trigger_puff", "puff", 0.05),
                ("write_output", "puff_b_selector", False),
            ],
        )

    def test_puff_train_holds_selector_and_repeats_pulses(self) -> None:
        daq = FakeDaqForPuff()
        logger = FakeLoggerForPuff()
        controller = StimulusController(daq=daq, logger=logger)
        context = SimpleNamespace(stimuli=controller, logger=logger)

        _deliver_puff_train(
            context=context,
            delivery={
                "channel": "puff",
                "duration_sec": 0.0001,
                "frequency_hz": 200.0,
                "selector_channel": "puff_b_selector",
                "selector_state": True,
                "selector_settle_sec": 0.0,
                "reset_selector_state": False,
            },
            total_duration_sec=0.012,
            label="test_train",
        )

        trigger_calls = [call for call in daq.calls if call[0] == "trigger_puff"]
        self.assertGreaterEqual(len(trigger_calls), 2)
        self.assertEqual(daq.calls[0], ("write_output", "puff_b_selector", True))
        self.assertEqual(daq.calls[-1], ("write_output", "puff_b_selector", False))

    def test_scene_dropout_keeps_then_drops_modality(self) -> None:
        context = SimpleNamespace(
            rng=random.Random(1),
            logger=FakeLoggerForPuff(),
            scene_assignment={"target": "A", "distractor": "B"},
        )
        phase = PreConditioningScenePhase(
            context=context,
            config={
                "_randomization": {
                    "dropout": {
                        "enabled": True,
                        "interval_sec": 1.0,
                        "dropped_modalities": ["screen"],
                        "dropout_duration_sec": [0.1, 0.1],
                    }
                }
            },
        )
        chunks: list[tuple[str, float, str | None]] = []
        phase._deliver_scene_chunk = lambda scene_id, duration_sec, dropped: chunks.append((scene_id, duration_sec, dropped))  # type: ignore[method-assign]

        phase._run_scene_with_dropout(label="pre", block_idx=0, scene_key="target", duration_sec=1.0)

        self.assertEqual(chunks[0][2], None)
        self.assertEqual(chunks[1][2], "screen")

    def test_scene_dropout_disabled_delivers_full_scene(self) -> None:
        context = SimpleNamespace(
            rng=random.Random(1),
            logger=FakeLoggerForPuff(),
            scene_assignment={"target": "A", "distractor": "B"},
        )
        phase = PreConditioningScenePhase(context=context, config={"_randomization": {"dropout": {"enabled": False}}})
        chunks: list[tuple[str, float, str | None]] = []
        phase._deliver_scene_chunk = lambda scene_id, duration_sec, dropped: chunks.append((scene_id, duration_sec, dropped))  # type: ignore[method-assign]

        phase._run_scene_with_dropout(label="pre", block_idx=0, scene_key="target", duration_sec=1.0)

        self.assertEqual(chunks, [("A", 1.0, None)])

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

    def test_config_validation_rejects_duplicate_output_channels(self) -> None:
        config = _minimal_valid_config()
        config["channels"]["digital_outputs"]["shock"] = "Dev1/port0/line7"

        with self.assertRaises(ConfigValidationError) as caught:
            validate_experiment_v2_config(config)
        self.assertIn("Duplicate physical output channel", str(caught.exception))

    def test_config_validation_rejects_negative_background_duration(self) -> None:
        config = _minimal_valid_config()
        config["background"] = {"enabled": True, "duration_sec": -1.0}

        with self.assertRaises(ConfigValidationError) as caught:
            validate_experiment_v2_config(config)
        self.assertIn("background.duration_sec", str(caught.exception))


def _minimal_valid_config() -> dict:
    return {
        "daq": {"enabled": False, "opto_mode": "arduino"},
        "channels": {
            "digital_outputs": {
                "puff_b_selector": "Dev1/port0/line7",
                "puff": "Dev1/port0/line5",
                "shock": "Dev1/port0/line0",
                "ir_led": "Dev1/port0/line1",
            },
            "digital_inputs": {},
            "analog_outputs": {"reward_valve": "Dev1/ao1"},
            "analog_inputs": {"lick": "Dev1/ai2"},
        },
        "stimuli": {
            "audio": {},
            "visual": {},
            "whisker": {"output_name": "puff"},
            "shock": {"output_name": "shock"},
            "opto": {
                "output_name": "opto",
                "arduino_pin": 9,
                "arduino_active_low": False,
                "arduino_reset_on_connect": False,
                "arduino_startup_wait_sec": 0.05,
            },
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
