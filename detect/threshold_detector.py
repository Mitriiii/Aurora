"""
Phase 3: rule-based / physics-threshold early-warning detector.

This is deliberately not machine learning. Real under-frequency and
under-voltage load-shedding schemes are rule-based too -- a threshold
detector grounded in the actual physics of the failure mode is a credible,
defensible MVP, not a placeholder for "real" detection.

It consumes the simulator's tick-by-tick PMU-style output stream in order,
exactly as it would arrive live. It never looks ahead: `update()` sees only
the current frame and the detector's own rolling history.

Tracked quantities, matching Section 4.4 of the build brief:
  - reactive power margin per generator, against Spain's real ±0.98 grid-code
    power-factor band, expressed as drift from each generator's own healthy
    baseline (captured in the first few ticks of the run) -- necessary
    because the stock Kundur benchmark dispatch is not itself tuned to a
    0.98 PF band, so an absolute-zero threshold would misfire on frame 1.
  - oscillation amplitude and growth rate on monitored bus voltages.
  - ROCOF (ties the schema together; in this event ROCOF itself only spikes
    at/after the generation trips, exactly as it did historically -- it is
    not the early signal, the reactive margin and oscillation growth are).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

PF_LIMIT = 0.98
TAN_PHI_LIMIT = math.tan(math.acos(PF_LIMIT))

BASELINE_TICKS = 5          # ticks used to establish the "healthy" reference
OSC_WINDOW_S = 3.0          # rolling window for oscillation amplitude
OSC_HISTORY_S = 9.0         # window used to judge growth vs damping (3 sub-windows)

MARGIN_DROP_THRESHOLD_PU = 0.9    # sustained drop from baseline reactive margin
OSC_GROWTH_MIN_RATIO = 1.15       # amplitude(t) / amplitude(t - window) to call it "growing"

# "Sustained" is judged over a short rolling window rather than requiring
# strict consecutive ticks -- the underlying signal is itself oscillatory
# (that's the whole point), so a strict-consecutive rule flickers on noise.
SUSTAIN_WINDOW_TICKS = 6
SUSTAIN_MIN_HITS = 4


@dataclass
class DetectorState:
    baseline_margin: dict[str, float] | None = None
    margin_history: deque = field(default_factory=lambda: deque(maxlen=2000))
    voltage_history: dict[str, deque] = field(default_factory=dict)
    ticks_seen: int = 0
    hit_window: deque = field(default_factory=lambda: deque(maxlen=SUSTAIN_WINDOW_TICKS))
    fired: bool = False
    fired_t: float | None = None
    fired_reasons: list[str] = field(default_factory=list)


class ThresholdDetector:
    def __init__(self, monitored_buses: list[str], dt: float):
        self.monitored_buses = monitored_buses
        self.dt = dt
        self.state = DetectorState()
        for b in monitored_buses:
            self.state.voltage_history[b] = deque(maxlen=int(OSC_HISTORY_S / dt) + 10)
        self._baseline_frames: list[dict] = []

    def _reactive_margin(self, frame: dict) -> dict[str, float]:
        margins = {}
        for gidx, p in frame["gen_p_pu"].items():
            q = frame["gen_q_pu"][gidx]
            qmax = abs(p) * TAN_PHI_LIMIT
            margins[gidx] = qmax - abs(q)
        return margins

    def _oscillation_amplitude(self, bus: str) -> float:
        hist = self.state.voltage_history[bus]
        n = int(OSC_WINDOW_S / self.dt)
        if len(hist) < n:
            return 0.0
        recent = list(hist)[-n:]
        return max(recent) - min(recent)

    def _oscillation_growth_ratio(self, bus: str) -> float:
        hist = self.state.voltage_history[bus]
        n = int(OSC_WINDOW_S / self.dt)
        if len(hist) < 3 * n:
            return 1.0
        vals = list(hist)
        recent = vals[-n:]
        older = vals[-3 * n:-2 * n]
        amp_recent = max(recent) - min(recent)
        amp_older = max(older) - min(older)
        if amp_older < 1e-4:
            return 1.0 if amp_recent < 1e-4 else 3.0
        return amp_recent / amp_older

    def update(self, frame: dict) -> dict:
        """Feed one tick. Returns a dict describing the detector's current
        read on the grid -- margins, oscillation state, and whether/why the
        danger flag has fired. Idempotent after firing (stays fired)."""
        self.state.ticks_seen += 1

        for b in self.monitored_buses:
            self.state.voltage_history[b].append(frame["bus_v_pu"].get(b, 1.0))

        margins = self._reactive_margin(frame)
        self.state.margin_history.append(margins)

        if self.state.baseline_margin is None:
            self._baseline_frames.append(margins)
            if len(self._baseline_frames) >= BASELINE_TICKS:
                keys = margins.keys()
                self.state.baseline_margin = {
                    k: sum(f[k] for f in self._baseline_frames) / len(self._baseline_frames)
                    for k in keys
                }

        result = {
            "t": frame["t"],
            "margins": margins,
            "margin_drop": {},
            "oscillation_amplitude": {b: self._oscillation_amplitude(b) for b in self.monitored_buses},
            "oscillation_growth": {b: self._oscillation_growth_ratio(b) for b in self.monitored_buses},
            "danger": self.state.fired,
            "fired_this_tick": False,
            "reasons": [],
        }

        if self.state.baseline_margin is None or self.state.fired:
            if self.state.fired:
                result["danger"] = True
            return result

        drop = {k: self.state.baseline_margin[k] - margins[k] for k in margins}
        result["margin_drop"] = drop
        worst_gen, worst_drop = max(drop.items(), key=lambda kv: kv[1])

        margin_condition = worst_drop > MARGIN_DROP_THRESHOLD_PU
        growth_condition = any(
            result["oscillation_growth"][b] > OSC_GROWTH_MIN_RATIO
            and result["oscillation_amplitude"][b] > 0.02
            for b in self.monitored_buses
        )

        self.state.hit_window.append(bool(margin_condition and growth_condition))

        if (len(self.state.hit_window) == SUSTAIN_WINDOW_TICKS
                and sum(self.state.hit_window) >= SUSTAIN_MIN_HITS):
            self.state.fired = True
            self.state.fired_t = frame["t"]
            reasons = [
                f"reactive power margin on GEN_{worst_gen} dropped {worst_drop:.2f} p.u. below its healthy "
                f"baseline (Spain's grid code ±0.98 power-factor band)",
                f"sustained, growing low-frequency oscillation on monitored buses "
                f"(growth ratio {max(result['oscillation_growth'].values()):.2f}x over {OSC_WINDOW_S:.0f}s windows)",
            ]
            self.state.fired_reasons = reasons
            result["fired_this_tick"] = True
            result["reasons"] = reasons
            result["danger"] = True

        return result

    @property
    def fired_t(self) -> float | None:
        return self.state.fired_t

    @property
    def fired_reasons(self) -> list[str]:
        return self.state.fired_reasons
