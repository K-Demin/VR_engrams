# VR Engrams Puff Task

This repository currently supports two execution paths:

- **Legacy pipeline (legacy/maintenance-only):** `main_pipeline.py` with legacy config formats.
- **v2 pipeline (production protocol path):** `run_experiment_v2.py` with `configs/experiment_v2.yaml`.

## Canonical run command (v2 production)

```bash
python run_experiment_v2.py configs/experiment_v2.yaml --animal-id M001 --session 1 --run 1
```

## Legacy pipeline status (legacy)

The following commands remain available for backward compatibility and historical experiments, but they are **legacy** and not the recommended production path:

```bash
python main_pipeline.py configs/experiment.yaml --animal m01
python main_pipeline.py configs/puff_task.yaml --animal m01
```

## v2 quick-start

1. Connect NI-DAQ hardware and verify the device name(s) used in config (for example `Dev1`).
2. Open and edit `configs/experiment_v2.yaml` for the current session.
3. Run the canonical command:
   ```bash
   python run_experiment_v2.py configs/experiment_v2.yaml --animal-id M001 --session 1 --run 1
   ```
4. Confirm session output appears under `logging.output_root` (default `./data`). Imaging-linked runs use BIDS-style `sub-<animal>/ses-<n>/func/` output.

## Task selection in v2

The v2 entrypoint is the same for the full protocol, decoder-only, fear/pre/post-only, fMRI-only, and bench/no-imaging runs. Task selection is config-driven: the scheduler runs phases whose YAML blocks are enabled and skips phases with `enabled: false`.

```bash
python run_experiment_v2.py configs/experiment_v2.yaml --animal-id M001 --session 1 --run 1
python run_experiment_v2.py configs/decoder_only.yaml --animal-id M001 --session 1 --run 1
python run_experiment_v2.py configs/fmri_opto.yaml --animal-id M001 --session 1 --run 1
python run_experiment_v2.py configs/experiment_v2.yaml --animal-id M001 --no-camera-sync
```

No task state machines from `new reference` are imported into the VR Engrams scheduler; that folder is used only as a device-interface reference.

## Direct stimulus tests

Use `tools/test_stimuli.py` to test one stimulus without running the scheduler:

```bash
python tools/test_stimuli.py configs/experiment_v2.yaml list
python tools/test_stimuli.py configs/experiment_v2.yaml visual --channel screen_a --duration-sec 2
python tools/test_stimuli.py configs/experiment_v2.yaml sound --frequency-hz 8000 --duration-sec 0.5
python tools/test_stimuli.py configs/experiment_v2.yaml puff --duration-sec 0.05
python tools/test_stimuli.py configs/experiment_v2.yaml puff-a --duration-sec 0.05 --train-duration-sec 5 --frequency-hz 1
python tools/test_stimuli.py configs/experiment_v2.yaml puff-b --duration-sec 0.05 --train-duration-sec 5 --frequency-hz 1
python tools/test_stimuli.py configs/experiment_v2.yaml reward --duration-ms 50
python tools/test_stimuli.py configs/experiment_v2.yaml ir-led --duration-sec 0.5
python tools/test_stimuli.py configs/experiment_v2.yaml opto --duration-sec 1 --frequency-hz 20 --pulse-width-ms 15 --armed
python tools/test_stimuli.py configs/experiment_v2.yaml shock --duration-sec 0.2 --armed
```

`puff-a` and `puff-b` run as pulse trains during whisker stimuli. Configure their train rates separately with `stimuli.whisker.puff_a_frequency_hz` and `stimuli.whisker.puff_b_frequency_hz` (default `1.0` Hz). `puff-b` uses the same main puff valve as `puff-a`, but first sets the side-selector solenoid high on `channels.digital_outputs.puff_b_selector` at `Dev1/port0/line7`. After the B train, the selector resets low to the A side. Add `--no-daq` to dry-run hardware outputs without touching NI/serial devices. `--armed` is only an explicit safety confirmation for opto and shock test commands.

For Puff B debugging, sweep selector timing and polarity without editing YAML:

```bash
python tools/test_stimuli.py configs/experiment_v2.yaml puff-selector --state high --hold-sec 2
python tools/test_stimuli.py configs/experiment_v2.yaml puff-b --duration-sec 0.05 --train-duration-sec 5 --frequency-hz 1 --selector-settle-sec 0.2
python tools/test_stimuli.py configs/experiment_v2.yaml puff-b --duration-sec 0.05 --train-duration-sec 5 --frequency-hz 1 --selector-state low
```

## What to edit before each run (top 10 parameters)

Edit these first in `configs/experiment_v2.yaml`:

1. **Phase repetitions (decoder):** `phases.decoder.reps_per_condition`
2. **Phase repetitions (pre-conditioning):** `phases.pre-conditioning.blocks_per_condition`
3. **Shock count range (fear conditioning):** `phases.fear conditioning.shocks_per_session`
4. **Post-conditioning repetitions:** `phases.post-conditioning.blocks_per_condition`
5. **fMRI total duration:** `phases.fMRI opto block design.total_duration_sec`
6. **Fear shock spacing:** `phases.fear conditioning.shock_spacing_sec`
7. **Puff duration:** `stimuli.whisker.duration_sec`
8. **Shock duration:** `stimuli.shock.duration_sec`
9. **Reward valve pulse width (ms):** set reward pulse timing in the hardware/config path used for reward delivery (convert ms to seconds where applicable).
10. **Opto train controls:** `stimuli.opto.frequency_hz`, `stimuli.opto.pulse_width_sec`, `stimuli.opto.arduino_port`, and `stimuli.opto.arduino_pin`.

### Channel mapping fields to verify while editing

- `channels.analog_inputs.lick`
- `channels.digital_outputs.puff`
- `channels.digital_outputs.puff_b_selector`
- `channels.digital_outputs.shock`
- `channels.digital_outputs.ir_led`
- `stimuli.opto.arduino_port` and `stimuli.opto.arduino_pin`

## Preflight checklist

Before clicking run:

- [ ] **NI device connected:** NI-DAQ is visible and channel strings resolve on this machine.
- [ ] **Channels valid:** All configured DI/DO/counter channels exist and are not reserved by other tasks.
- [ ] **Displays mapped:** Visual display / trigger mapping is correct for the intended monitor/projector.
- [ ] **Laser arm state correct:** Laser/opto source is armed only when intended and interlocks are satisfied.

## Hardware overview

- **Lick / valve subsystem**
  - Lick detection defaults to NI analog input `Dev1/ai2` with `session.lick_logic_mode: low_is_lick`.
  - Reward valve output is configured independently from whisker puff output and uses the v2 analog-output pulse path by default.
  - Reward calibration target is ~3-3.5 uL per lick; default pulse width is 50 ms and should be calibrated per rig.
- **Camera / imaging sync subsystem**
  - When `imaging.enabled: true`, PC2 sends `PING`, `TIMESYNC`, `START <pc1_func_dir>|<bids_stem>|<led_cycle>`, and `STOP` to the PC1 camera listener.
  - PC1 Master-9 fire time is used as session `t=0` for event onsets.
  - Optional IR LED pulses are emitted through `channels.digital_outputs.ir_led` at run start, imaging-start marker, imaging-stop marker, and run end.
- **Puff subsystem**
  - Air puff TTL is sent through an NI digital output line.
  - Puff duration and side are controlled from config.
- **Sound subsystem**
  - Tone A/B can be played through `sounddevice` backend (`stimuli.audio.enabled: true`).
  - Fallback mode logs and sleeps when audio dependencies are unavailable.
- **Visual subsystem**
  - PsychoPy screen rendering is supported (`stimuli.visual.use_psychopy: true`).
  - `stimuli.visual.screen_index` selects which monitor/screen receives VR scene rendering.
- **Shock subsystem**
  - Shock channel exists in config and can be enabled/disabled per protocol.
- **Optogenetics subsystem**
  - Production path uses Arduino serial train generation via `daq.opto_mode: arduino`.
  - The Arduino firmware drives opto TTL on digital pin 9 by default (`stimuli.opto.arduino_pin: 9` documents this mapping).
  - The current rig is configured as active-high (`stimuli.opto.arduino_active_low: false`): D9 LOW is laser off, D9 HIGH is laser on.
  - Runtime sends `PING`, `POLARITY ACTIVE_HIGH`, `OFF`, then `TRAIN <freq_hz> <pulse_ms> <duration_ms>` to Arduino firmware.
  - Serial opens with Arduino auto-reset disabled by default (`stimuli.opto.arduino_reset_on_connect: false`) to avoid a brief laser-on window before the first command.
  - Serial settings live in `stimuli.opto.arduino_port`, `stimuli.opto.arduino_baud`, `stimuli.opto.arduino_timeout_sec`.
  - Pulse shape is still set by `stimuli.opto.frequency_hz` and `stimuli.opto.pulse_width_sec`.
  - Supporting tools:
    - Arduino firmware: `tools/arduino_opto_firmware/arduino_opto_firmware.ino`
    - Python sender: `tools/arduino_opto_sender.py`
    - Example command:
      ```bash
      python tools/arduino_opto_sender.py --port COM3 --pin 9 --mode ping
      python tools/arduino_opto_sender.py --port COM3 --pin 9 --mode off
      python tools/arduino_opto_sender.py --port COM3 --pin 9 --mode block --freq-hz 20 --pulse-ms 15 --on-sec 30 --off-sec 30 --total-sec 3600
      ```
  - If the laser stays on after a test, turn the laser key/interlock off first. Then upload `tools/arduino_opto_firmware/arduino_opto_firmware.ino`; the current firmware boots D9 LOW so the laser is off before any serial command.
  - If a brief flash still happens exactly when a serial program opens the port, that is during Arduino reset/high-impedance time and cannot be fully solved in Python. Add a physical TTL pull-down from D9 to GND or disable auto-reset on the Arduino for hard safety.

## v2 protocol mapping (implementation status)

The v2 scheduler runs the following phases in order:

1. `decoder` (isolated conditions: screen/sound/whisker/no-stim)
2. `pre-conditioning` (scene blocks with modality dropout + sham opto condition)
3. `fear conditioning` (continuous target scene + discrete NI-triggered shocks)
4. `post-conditioning` (same scene blocks with active opto condition)
5. `fMRI opto block design` (30 s on/off Arduino opto blocks)

Phase keys in YAML are normalized to canonical internal names (`decoder`, `pre`, `fear`, `post`, `fmri`) so both legacy and descriptive names are accepted.
Dropout timing is driven by `randomization.dropout.*` (interval, modalities, duration range).

## NI channel mapping and calibration notes

Default mapping is defined in `configs/experiment.yaml`:

- `lick_valve.lick_ni_di_channel`: `Dev1/port0/line1`
- `lick_valve.reward_valve_ni_do_channel`: `Dev1/port0/line4`
- `puff.ni_do_channel`: `Dev1/port0/line5`
- `visual.trigger_ni_do_channel`: `Dev1/port0/line6`
- `shock.ni_do_channel`: `Dev1/port0/line0`
- Legacy opto configs are historical; the v2 production opto path uses Arduino D9, not an NI DO line.

Calibration note for liquid reward valve:

- Start with **45–55 ms** open time and verify by gravimetric calibration.
- Current default in config is **50 ms**, used for approximately **3–3.5 µL** delivery on the reference setup.

For the v2 path, use these corresponding fields in `configs/experiment_v2.yaml`:

- `session.reward_output_name` (logical NI output used for reward valve)
- `stimuli.reward_valve.duration_ms` (valve opening duration in milliseconds)
- `stimuli.opto.frequency_hz` and `stimuli.opto.pulse_width_sec` (Arduino train defaults)
- `stimuli.opto.arduino_port`, `stimuli.opto.arduino_baud`, `stimuli.opto.arduino_pin`, `stimuli.opto.arduino_active_low`, and `stimuli.opto.arduino_reset_on_connect`

## Mouse-level randomization (target scene A/B assignment)

`randomization_constraints.mouse_level_scene_assignment` sets the assignment policy:

- At session start, each mouse is assigned one fixed mapping:
  - target = A, distractor = B **or**
  - target = B, distractor = A
- The mapping is held constant across all phases in that session.

This prevents within-session scene remapping while balancing assignment across mice.

## Phase-by-phase protocol defaults (v2 engram workflow)

| Phase | Default duration / count | Purpose |
|---|---:|---|
| Decoder | 60 reps/condition, 2–10 s event + 2–10 s ITI | Isolated modality representations |
| Pre-conditioning | 4 blocks/condition | Baseline target/non-target/empty/opto-sham |
| Fear conditioning | 6–8 min scene, 3–5 shocks | Target scene + aversive pairing |
| Post-conditioning | 4 blocks/condition | Re-test + active opto condition |
| fMRI opto | 30 s ON / 30 s OFF for 1 h | Block-design opto-only protocol |

## Expected output files

Imaging-linked runs create BIDS-style session folders:

- PC2: `<bids_root_pc2>/sub-<animal>/ses-<n>/func/`
- PC1: `<bids_root_pc1>/sub-<animal>/ses-<n>/func/`

Expected files include:

- `events.jsonl` and `events.csv` (existing v2 compatibility logs)
- `behavior_log.csv` (lick monitor and behavioural events)
- `sub-<animal>_ses-<n>_task-<task>_run-<run>_events.tsv` (BIDS-style events for imaging alignment)
- `sub-<animal>_ses-<n>_task-<task>_run-<run>_config.yaml` (effective config snapshot)
- `sub-<animal>_ses-<n>_task-<task>_run-<run>_clock_sync.yaml` (PC1/PC2 clock offset and imaging start metadata)
- `*_frames.tsv` (camera/frame timing; produced by the PC1 camera computer)

The legacy root `main_pipeline.py` remains historical/maintenance-only. New production work should stay on `run_experiment_v2.py` and `src/vr_engrams`.
