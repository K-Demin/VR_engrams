# VR Engrams v2 Package Boundary

This document introduces an **interface-first package boundary** under:

- `src/vr_engrams_v2/`

The legacy package (`src/vr_engrams/`) and all legacy files remain unchanged so teams can migrate incrementally.

## Goals

- Keep existing experiments runnable on the current code path.
- Introduce narrow, reusable interfaces for hardware and phase orchestration.
- Make small improvements (like lick monitor upgrades or stimulus decorators) reusable in both pipelines.

## Core Interfaces

The new protocol interfaces are defined in `src/vr_engrams_v2/interfaces.py`:

- `IDaqController`
- `IStimulusController`
- `ILickMonitor`
- `IExperimentLogger`
- `IPhase`

These are intentionally small and should be the only contracts that most new v2 components depend on.

## Reusable Components

### 1) Improved lick monitor

- Module: `src/vr_engrams_v2/components/improved_lick_monitor.py`
- Class: `ImprovedLickMonitor`
- Highlights:
  - Rising-edge detection (prevents repeated events while signal is held high)
  - Debounce window (`debounce_sec`)
  - Optional reward callback support

### 2) Opto counter controller

- Module: `src/vr_engrams_v2/components/opto_counter_controller.py`
- Class: `OptoCounterStimulusController`
- Highlights:
  - Decorates any `IStimulusController`
  - Tracks number of opto deliveries (`opto_count`)
  - Emits `opto_stim_counter_incremented` logger events

## Legacy Adapters (No Full Migration Required)

Adapters are provided in `src/vr_engrams_v2/adapters/legacy_pipeline.py` to bridge legacy classes into v2 interfaces:

- `LegacyDaqAdapter`
- `LegacyStimulusAdapter`
- `LegacyLoggerAdapter`
- `LegacyLickMonitorAdapter`

There is also a focused factory for adopting only the improved lick monitor in legacy code:

- `build_improved_lick_monitor_for_legacy(...)`

### Example: use improved lick monitor in legacy pipeline

```python
from vr_engrams_v2.adapters import build_improved_lick_monitor_for_legacy

lick_monitor = build_improved_lick_monitor_for_legacy(
    daq=legacy_daq,
    logger=legacy_logger,
    lick_input_name="lick",
    reward_callback=reward_fn,
)

lick_monitor.start(reward_on_lick=True)
```

## Migration Notes

1. **Start at boundaries**
   - When writing new logic, depend on v2 interfaces (`IDaqController`, `IStimulusController`, etc.) rather than concrete legacy classes.

2. **Wrap existing implementations**
   - Use legacy adapters to provide v2 interface objects while existing runtime wiring stays untouched.

3. **Migrate per component, not per pipeline**
   - Upgrade one piece at a time (e.g., lick monitor, then opto controller decorator) without rewriting scheduler/task code.

4. **Add new phases behind `IPhase`**
   - New phase modules should expose a small `IPhase` implementation for composability and testability.

5. **Retire adapters last**
   - Once a legacy component has a native v2 implementation and all call sites use it, adapters can be removed safely.

## Suggested Next Step

Introduce a thin v2 scheduler that accepts a list of `IPhase` instances and orchestrates them, while still using legacy adapters for hardware until native v2 controllers are ready.
