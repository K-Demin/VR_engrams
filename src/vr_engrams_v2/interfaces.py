from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IDaqController(Protocol):
    """Digital IO interface used by pipeline components."""

    def pulse_output(self, name: str, duration_sec: float) -> None:
        ...

    def write_output(self, name: str, state: bool) -> None:
        ...

    def read_input(self, name: str) -> bool:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class IStimulusController(Protocol):
    """Stimulus delivery API used by phases."""

    def deliver_visual(self, channel: str, duration_sec: float) -> None:
        ...

    def deliver_sound(self, frequency_hz: float, duration_sec: float, side: str = "both") -> None:
        ...

    def deliver_puff(self, channel: str, duration_sec: float) -> None:
        ...

    def deliver_shock(self, channel: str, duration_sec: float, amplitude: float | None = None) -> None:
        ...

    def deliver_opto(self, channel: str, duration_sec: float, power_mw: float | None = None) -> None:
        ...


@runtime_checkable
class ILickMonitor(Protocol):
    """Async lick monitor behavior used in training tasks."""

    def start(self, reward_on_lick: bool = False) -> None:
        ...

    def stop(self) -> None:
        ...


@runtime_checkable
class IExperimentLogger(Protocol):
    """Structured event logging interface."""

    def snapshot_parameters(self) -> None:
        ...

    def log_event(self, event: str, **fields: Any) -> None:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class IPhase(Protocol):
    """Executable experiment phase unit."""

    @property
    def name(self) -> str:
        ...

    def run(self) -> None:
        ...
