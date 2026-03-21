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

1. **Phase repetitions (decoder):** `phases.decoder.trials`
2. **Phase repetitions (pre-conditioning):** `phases.pre-conditioning.trials`
3. **Phase repetitions (fear conditioning):** `phases.fear conditioning.trials`
4. **Phase repetitions (post-conditioning):** `phases.post-conditioning.trials`
5. **Phase repetitions (fMRI opto block):** `phases.fMRI opto block design.trials`
6. **Timing / shock spacing via ITI:** `phases.fear conditioning.iti_sec`
7. **Puff duration:** `stimuli.whisker.duration_sec`
8. **Shock duration:** `stimuli.shock.duration_sec`
9. **Reward valve pulse width (ms):** set reward pulse timing in the hardware/config path used for reward delivery (convert ms to seconds where applicable).
10. **Opto train controls:** `phases.fMRI opto block design.opto_duration_sec` and hardware train settings in DAQ (counter frequency/pulse width) when applicable.

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
  - Reward valve output is reserved in config for calibrated liquid delivery.
- **Puff subsystem**
  - Air puff TTL is sent through an NI digital output line.
  - Puff duration and side are controlled from config.
- **Sound subsystem**
  - Left/right tones are played through `sounddevice` according to trial rules.
- **Visual subsystem**
  - Visual trigger/display metadata is configured for scene A/B experiments.
- **Shock subsystem**
  - Shock channel exists in config and can be enabled/disabled per protocol.
- **Optogenetics subsystem**
  - Opto trigger channel and pulse metadata are included in config and default to disabled.

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

## Mouse-level randomization (target scene A/B assignment)

`randomization_constraints.mouse_level_scene_assignment` sets the assignment policy:

- At session start, each mouse is assigned one fixed mapping:
  - target = A, distractor = B **or**
  - target = B, distractor = A
- The mapping is held constant across all phases in that session.

This prevents within-session scene remapping while balancing assignment across mice.

## Phase-by-phase protocol defaults

| Phase | Default duration / count | Purpose |
|---|---:|---|
| Baseline | 15 s, 1 repetition | Quiet pre-task imaging period |
| Acquisition | 40 trials | Main task with audio cue, delay, puff, response window |
| ITI (within acquisition) | 2.0–6.0 s | Variable inter-trial interval |
| Cue delay (within acquisition) | 1.5 s | No-lick period after cue |
| Response window (within acquisition) | 0.8 s | Lick detection window |
| Timeout (early lick) | 5.0 s | Penalty period |
| Extinction | disabled (0 trials) | Reserved optional phase |

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
