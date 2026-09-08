"""
Physics-derived collapse criterion.

Previously, "the grid has collapsed" was asserted by the scenario script
itself -- a Toggle hardcoded to trip three generators and three lines at a
fixed time budget (trip_1_t + 27s), regardless of what the simulation was
actually doing. That is a scripted animation, not a result, and it directly
violates BUILD_PROMPT.md's Phase 4 acceptance bar ("a genuine counterfactual,
not a scripted animation").

This module replaces that assertion with an honest definition of collapse,
grounded in real protective-relay logic: collapse is declared when ANY of
the following holds, sustained for at least SUSTAIN_S seconds (so a single
noisy sample or a legitimate, recoverable electromechanical swing doesn't
get misread as collapse):

  1. The TDS solver itself fails to converge -- a genuine numerical
     inability to find a valid operating point. The strongest signal
     there is, and the only criterion the previous version relied on.
  2. System frequency leaves a protective band. The real event's own UFLS
     fired below 48.0 Hz; the upper bound mirrors typical over-frequency
     generator trip settings (~51.5-52 Hz in real grid codes).
  3. Any monitored bus voltage leaves a protective band. Wide enough
     (0.5-1.5 p.u.) to not flag legitimate large transient swings, tight
     enough to catch a genuinely invalid, unrecoverable operating point.

Whether and when collapse happens is now something the simulation produces
tick by tick, not something scenario code decides in advance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FREQ_MIN_HZ = 47.5
FREQ_MAX_HZ = 52.5
V_MIN_PU = 0.5
V_MAX_PU = 1.5
SUSTAIN_S = 0.5


@dataclass
class CollapseMonitor:
    monitored_buses: list
    dt: float
    violation_streak: int = 0
    collapsed: bool = False
    collapsed_t: float | None = None
    collapse_reason: str | None = None

    def __post_init__(self):
        self.n_sustain = max(1, int(round(SUSTAIN_S / self.dt)))

    def update(self, frame: dict, tds_converged: bool) -> bool:
        """Feed one tick. Returns True once collapse has been declared
        (sticky -- stays True on every subsequent call)."""
        if self.collapsed:
            return True

        if not tds_converged:
            self.collapsed = True
            self.collapsed_t = frame["t"]
            self.collapse_reason = "TDS solver failed to converge -- no valid operating point found"
            return True

        freq = frame.get("freq_hz", 50.0) or 0.0
        voltages = {b: frame["bus_v_pu"].get(b, 1.0) for b in self.monitored_buses}

        freq_violation = not (FREQ_MIN_HZ <= freq <= FREQ_MAX_HZ)
        bad_buses = {b: v for b, v in voltages.items() if not (V_MIN_PU <= v <= V_MAX_PU)}

        if freq_violation or bad_buses:
            self.violation_streak += 1
        else:
            self.violation_streak = 0

        if self.violation_streak >= self.n_sustain:
            self.collapsed = True
            self.collapsed_t = round(frame["t"] - (self.n_sustain - 1) * self.dt, 3)
            reasons = []
            if freq_violation:
                reasons.append(f"frequency {freq:.2f} Hz outside [{FREQ_MIN_HZ}, {FREQ_MAX_HZ}] Hz")
            if bad_buses:
                detail = ", ".join(f"bus {b}={v:.3f} p.u." for b, v in bad_buses.items())
                reasons.append(f"voltage outside [{V_MIN_PU}, {V_MAX_PU}] p.u. ({detail})")
            self.collapse_reason = f"sustained {SUSTAIN_S}s: " + "; ".join(reasons)
            return True

        return False
