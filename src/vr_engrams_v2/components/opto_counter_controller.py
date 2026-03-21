from __future__ import annotations

from dataclasses import dataclass, field

from vr_engrams_v2.interfaces import IExperimentLogger, IStimulusController


@dataclass
class OptoCounterStimulusController(IStimulusController):
    """Decorator that counts optogenetic stim calls while delegating behavior."""

    inner: IStimulusController
    logger: IExperimentLogger
    opto_count: int = field(default=0, init=False)

    def deliver_visual(self, channel: str, duration_sec: float) -> None:
        self.inner.deliver_visual(channel, duration_sec)

    def deliver_sound(self, frequency_hz: float, duration_sec: float, side: str = "both") -> None:
        self.inner.deliver_sound(frequency_hz, duration_sec, side=side)

    def deliver_puff(self, channel: str, duration_sec: float) -> None:
        self.inner.deliver_puff(channel, duration_sec)

    def deliver_shock(self, channel: str, duration_sec: float, amplitude: float | None = None) -> None:
        self.inner.deliver_shock(channel, duration_sec, amplitude=amplitude)

    def deliver_opto(self, channel: str, duration_sec: float, power_mw: float | None = None) -> None:
        self.opto_count += 1
        self.logger.log_event(
            "opto_stim_counter_incremented",
            opto_count=self.opto_count,
            channel=channel,
            duration_sec=duration_sec,
            power_mw=power_mw,
        )
        self.inner.deliver_opto(channel, duration_sec, power_mw=power_mw)
