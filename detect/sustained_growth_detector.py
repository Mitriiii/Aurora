"""
Recalibrated/redesigned detector for the IEEE 39-bus network.

WHY NOT REUSE detect.threshold_detector.ThresholdDetector AS-IS: that
detector (validated and left untouched on Kundur) uses a PURE MAGNITUDE
threshold on reactive-margin drop from a fixed t=0 baseline
(MARGIN_DROP_THRESHOLD_PU=0.9), combined with a short-window (3s)
oscillation-growth check, sustained for only ~0.6s. On this network it
false-fires on both non-collapsing isolation counterfactuals within the
first 5-12 seconds: ordinary AVR transients on generators not even under
fault briefly exceed 0.9 p.u. of drop. It has no concept of "still
worsening vs. settled into a new stable equilibrium."

DIAGNOSIS, done properly before picking a fix direction (see the session's
diagnostic scripts, not reproduced as committed code):

1. Plotted bus 30's voltage (the bus that actually crosses the collapse
   threshold in the combined fault) in the excitation-alone counterfactual
   against the combined fault. The two are NEARLY IDENTICAL for the first
   ~55-57 seconds -- same oscillation, same envelope, same climb from
   ~1.05 to ~1.45 p.u.

2. A first attempt at a trend-based fix on the ORIGINAL reactive-margin
   metric (comparing a smoothed signal now to itself 10s ago, firing after
   3s sustained growth) STILL false-fired at t~22s on both benign
   counterfactuals: that early climb is shared by all three scenarios
   (everything is ramping toward a new operating point at that point), and
   there is no way to know, causally, at t=22s whether it will keep going
   or plateau.

3. Switched the tracked quantity from the P/Q-derived reactive-margin
   proxy to bus voltage directly (the actual quantity detect.collapse_monitor
   .CollapseMonitor uses as ground truth) and re-examined the smoothed
   (2s) trace for bus 30 out past t=60s. The margin proxy turned out NOT to
   discriminate at all here -- smoothed margin-drop for generator 30
   oscillates in the same 15-21 p.u. band in BOTH the excitation-alone and
   combined cases, all the way to and past the combined case's own t=66.5s
   collapse. It is a reasonable proxy for Kundur's fault mechanism but is
   not tightly coupled to what drives collapse in this one. Voltage is:
   smoothed bus-30 voltage sits in the same ~1.44-1.47 p.u. band in both
   cases through about t=60s, then the excitation-alone case stays in that
   band (1.4633 -> 1.4488 -> 1.4613 at t=62/64/66) while the combined case
   breaks decisively upward (1.4660 -> 1.4805 -> 1.4926 at the same times).

CONCLUSION: no causal detector can discriminate these two futures before
they actually start to diverge (~t=60-62s in this scenario) -- a property
of the physics, not a tuning failure, and this network's actual "signal"
lives in bus voltage, not the P/Q-based reactive-margin proxy that worked
for Kundur. The right criterion is "did the tracked voltage look like it
had plateaued, then break past that plateau" -- not "is it rising," which
both futures satisfy equally for a long shared stretch.

DESIGN: track smoothed (SMOOTH_WINDOW_S) voltage on each monitored bus.
Using three consecutive PLATEAU_WINDOW_S-long windows ending at the
current tick -- [t-3W,t-2W], [t-2W,t-W], [t-W,t] -- call the middle window
"plateaued" if its max didn't exceed the one before it by more than
PLATEAU_TOL_PU, and fire if the current window's max then exceeds the
plateaued window's max by BREAKOUT_MIN_PU. Evaluation only starts once a
bus's window max has already exceeded MIN_STRESS_PU at least once -- a
real precondition (only look for a resumed climb once the bus is already
meaningfully elevated), not a disguised timing hack. Deliberately a late
detector: it cannot and should not fire before the real divergence.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

BASELINE_TICKS = 5             # ticks used to establish each bus's healthy baseline voltage
SMOOTH_WINDOW_S = 2.0          # smooths out within-cycle oscillation before comparison
PLATEAU_WINDOW_S = 6.0         # roughly one observed oscillation cycle (~4-5s) plus margin
PLATEAU_TOL_PU = 0.01          # max growth allowed between the two PRIOR windows to call it "plateaued"
BREAKOUT_MIN_PU = 0.015        # required new-high margin over the prior window's max to call it a breakout
MIN_STRESS_PU = 1.30           # don't evaluate plateau/breakout until this bus's voltage has already
                                # climbed meaningfully above nominal -- a real precondition ("only look
                                # for a resumed climb once already elevated"), not a timing hack


@dataclass
class BusState:
    baseline: float | None = None
    baseline_frames: list = field(default_factory=list)
    raw_history: deque = field(default_factory=lambda: deque(maxlen=4000))
    smoothed_history: deque = field(default_factory=lambda: deque(maxlen=4000))


class SustainedGrowthDetector:
    """Fires when the WORST monitored bus's smoothed voltage sets a new
    high that breaks past a prior apparent plateau -- not merely "is
    rising," which both the danger case and (for a long shared stretch)
    the benign cases satisfy equally. No hindsight: every quantity is
    computed only from ticks seen so far."""

    def __init__(self, monitored_buses: list[str], dt: float):
        self.monitored_buses = monitored_buses
        self.dt = dt
        self.smooth_n = max(1, int(round(SMOOTH_WINDOW_S / dt)))
        self.window_n = max(1, int(round(PLATEAU_WINDOW_S / dt)))
        self.buses: dict[str, BusState] = {b: BusState() for b in monitored_buses}
        self.fired = False
        self.fired_t: float | None = None
        self.fired_reasons: list[str] = []

    def _window_max(self, hist: deque, start_from_end: int, length: int) -> float | None:
        n = len(hist)
        end = n - start_from_end + length
        begin = n - start_from_end
        if begin < 0 or end > n or begin >= end:
            return None
        vals = list(hist)[begin:end]
        return max(vals) if vals else None

    def update(self, frame: dict) -> dict:
        if self.fired:
            return {"t": frame["t"], "danger": True, "fired_this_tick": False, "reasons": []}

        worst_bus, worst_breakout = None, float("-inf")

        for b in self.monitored_buses:
            v = frame["bus_v_pu"].get(b)
            if v is None:
                continue

            st = self.buses[b]
            if st.baseline is None:
                st.baseline_frames.append(v)
                if len(st.baseline_frames) >= BASELINE_TICKS:
                    st.baseline = sum(st.baseline_frames) / len(st.baseline_frames)
                continue

            st.raw_history.append(v)
            smoothed = sum(list(st.raw_history)[-self.smooth_n:]) / min(len(st.raw_history), self.smooth_n)
            st.smoothed_history.append(smoothed)

            w = self.window_n
            max_now = self._window_max(st.smoothed_history, w, w)
            max_prior = self._window_max(st.smoothed_history, 2 * w, w)
            max_prior2 = self._window_max(st.smoothed_history, 3 * w, w)
            if max_now is None or max_prior is None or max_prior2 is None:
                continue
            if max_prior < MIN_STRESS_PU:
                continue

            plateaued_before = (max_prior - max_prior2) < PLATEAU_TOL_PU
            breakout = max_now - max_prior
            if plateaued_before and breakout > worst_breakout:
                worst_breakout, worst_bus = breakout, b

        if worst_bus is None:
            return {"t": frame["t"], "danger": False, "fired_this_tick": False, "reasons": []}

        result = {"t": frame["t"], "danger": False, "fired_this_tick": False, "reasons": [],
                  "worst_bus": worst_bus, "worst_breakout": worst_breakout}

        if worst_breakout > BREAKOUT_MIN_PU:
            self.fired = True
            self.fired_t = frame["t"]
            self.fired_reasons = [
                f"bus {worst_bus} voltage appeared to plateau, then broke past that plateau by "
                f"{worst_breakout:.4f} p.u. in the last {PLATEAU_WINDOW_S:.0f}s -- not a continuation "
                f"of an already-shared climb, a genuine new high after an apparent settle"
            ]
            result["danger"] = True
            result["fired_this_tick"] = True
            result["reasons"] = self.fired_reasons

        return result
