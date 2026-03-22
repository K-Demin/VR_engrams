# VR Engrams Puff Task

This repository currently supports two execution paths:

- **Legacy pipeline (legacy/maintenance-only):** `main_pipeline.py` with legacy config formats.
- **v2 pipeline (production protocol path):** `run_experiment_v2.py` with `configs/experiment_v2.yaml`.

## Canonical run command (v2 production)

```bash
python run_experiment_v2.py configs/experiment_v2.yaml --animal-id M001
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
   python run_experiment_v2.py configs/experiment_v2.yaml --animal-id M001
   ```
4. Confirm session output appears under `logging.output_root` (default `./data`).

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
10. **Opto train controls:** `stimuli.opto.frequency_hz`, `stimuli.opto.pulse_width_sec`, and `channels.counter_outputs.laser_clock`.

### Channel mapping fields to verify while editing

- `channels.digital_inputs.lick`
- `channels.digital_outputs.puff`
- `channels.digital_outputs.shock`
- `channels.digital_outputs.opto`
- `channels.counter_outputs.laser_clock`

## Preflight checklist

Before clicking run:

- [ ] **NI device connected:** NI-DAQ is visible and channel strings resolve on this machine.
- [ ] **Channels valid:** All configured DI/DO/counter channels exist and are not reserved by other tasks.
- [ ] **Displays mapped:** Visual display / trigger mapping is correct for the intended monitor/projector.
- [ ] **Laser arm state correct:** Laser/opto source is armed only when intended and interlocks are satisfied.

## Hardware overview

- **Lick / valve subsystem**
  - Lick detection is read via NI digital input.
  - Reward valve output is configured independently from whisker puff output.
  - Reward calibration target is ~3–3.5 µL per lick; default pulse width is 50 ms and should be calibrated per rig.
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
  - Opto train supports two regimes via `daq.opto_mode`:
    - `dio` (default): pulse train on digital output line (`stimuli.opto.output_name`)
    - `counter`: NI counter-generated train (`channels.counter_outputs.laser_clock`)
  - Default train is 20 Hz with 15 ms pulse width (configurable in `stimuli.opto`).
  - Direct Arduino mode (no NI train generation) is available via tools:
    - Arduino firmware: `tools/arduino_opto_firmware.ino`
    - Python sender: `tools/arduino_opto_sender.py`
    - Default serial port is `COM3` (override with `--port` if needed)
    - Example command:
      ```bash
      python tools/arduino_opto_sender.py --port COM3 --mode block --freq-hz 20 --pulse-ms 15 --on-sec 30 --off-sec 30 --total-sec 3600
      ```

## v2 protocol mapping (implementation status)

The v2 scheduler runs the following phases in order:

1. `decoder` (isolated conditions: screen/sound/whisker/no-stim)
2. `pre-conditioning` (scene blocks with modality dropout + sham opto condition)
3. `fear conditioning` (continuous target scene + discrete NI-triggered shocks)
4. `post-conditioning` (same scene blocks with active opto condition)
5. `fMRI opto block design` (30 s on/off style hardware-timed opto blocks)

Phase keys in YAML are normalized to canonical internal names (`decoder`, `pre`, `fear`, `post`, `fmri`) so both legacy and descriptive names are accepted.
Dropout timing is driven by `randomization.dropout.*` (interval, modalities, duration range).

## NI channel mapping and calibration notes

Default mapping is defined in `configs/experiment.yaml`:

- `lick_valve.lick_ni_di_channel`: `Dev1/port0/line1`
- `lick_valve.reward_valve_ni_do_channel`: `Dev1/port0/line4`
- `puff.ni_do_channel`: `Dev1/port0/line5`
- `visual.trigger_ni_do_channel`: `Dev1/port0/line6`
- `shock.ni_do_channel`: `Dev1/port0/line7`
- `opto.ni_do_channel`: `Dev1/port1/line0`

Calibration note for liquid reward valve:

- Start with **45–55 ms** open time and verify by gravimetric calibration.
- Current default in config is **50 ms**, used for approximately **3–3.5 µL** delivery on the reference setup.

For the v2 path, use these corresponding fields in `configs/experiment_v2.yaml`:

- `session.reward_output_name` (logical NI output used for reward valve)
- `stimuli.reward_valve.duration_sec` (valve opening duration)
- `stimuli.opto.frequency_hz` and `stimuli.opto.pulse_width_sec` (hardware counter train defaults)
- `channels.counter_outputs.laser_clock` (NI counter channel used for opto trains)

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

Each run creates a session folder at:

- PC2: `<base_path_pc2>/<animal>/<YYYY-MM-DD>/puff_task_<HH-MM-SS>/`
- PC1: `<base_path_pc1>/<animal>/<YYYY-MM-DD>/puff_task_<HH-MM-SS>/`

Expected files include:

- `behaviour_log.csv` (behavioural events)
- `frame_log.csv` (camera/frame timing; produced by camera computer)
- `config_used.yaml` (**immutable effective config snapshot**)
- `config_used.sha256` (digest for provenance/verification)

`config_used.yaml` is the effective runtime config (including runtime overrides like animal ID), written once at session start and made read-only when filesystem permissions allow.
