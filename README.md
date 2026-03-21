# VR Engrams Puff Task

This repository runs a head-fixed behavioural pipeline with NI-driven stimuli and synchronized camera acquisition.

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

## Run commands

Primary run command (new grouped config):

```bash
python main_pipeline.py configs/experiment.yaml --animal m01
```

Legacy config remains supported:

```bash
python main_pipeline.py configs/puff_task.yaml --animal m01
```

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
