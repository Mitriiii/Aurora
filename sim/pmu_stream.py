"""
Formats one simulation tick as a synchrophasor-style record, following the
shape of real IEEE C37.118.2 PMU data (Section 5 of the build brief): a
GPS-synchronized timestamp, voltage/current phasors, frequency, ROCOF,
analog channels, digital status flags, and a data-quality word.

This is SIMULATED data throughout -- it never touches a real PMU or SCADA
feed. The schema is followed for realism, not because it is wired to real
hardware.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

PMU_RATE_HZ = 50  # Spain is a 50 Hz system; report at a standard C37.118 rate

MONITORED_BUSES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]   # full topology, for the live network diagram
DETECTOR_BUSES = [7, 8, 9]                          # tie-line + Area-2 buses: where the real PMU gap was
MONITORED_BRANCHES = [
    "Line_0", "Line_1", "Line_2", "Line_3", "Line_4", "Line_5", "Line_6",
    "Line_7", "Line_8", "Line_9", "Line_10", "Line_11", "Line_12", "Line_13", "Line_14",
]


@dataclass
class PmuFrame:
    t: float
    freq_hz: float
    rocof_hz_s: float
    bus_v_pu: dict[str, float]
    bus_angle_deg: dict[str, float]
    branch_p_pu: dict[str, float]
    branch_q_pu: dict[str, float]
    gen_p_pu: dict[str, float]
    gen_q_pu: dict[str, float]
    gen_omega_pu: dict[str, float]
    data_quality: str = "VALID"     # VALID | STALE | MISSING -- dramatizes the real PMU gap
    status_flags: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 3),
            "freq_hz": round(self.freq_hz, 4),
            "rocof_hz_s": round(self.rocof_hz_s, 5),
            "bus_v_pu": {k: round(v, 4) for k, v in self.bus_v_pu.items()},
            "bus_angle_deg": {k: round(v, 3) for k, v in self.bus_angle_deg.items()},
            "branch_p_pu": {k: round(v, 4) for k, v in self.branch_p_pu.items()},
            "branch_q_pu": {k: round(v, 4) for k, v in self.branch_q_pu.items()},
            "gen_p_pu": {k: round(v, 4) for k, v in self.gen_p_pu.items()},
            "gen_q_pu": {k: round(v, 4) for k, v in self.gen_q_pu.items()},
            "gen_omega_pu": {k: round(v, 5) for k, v in self.gen_omega_pu.items()},
            "data_quality": self.data_quality,
            "status_flags": self.status_flags,
        }


def _line_flow(ss, line_idx: str) -> tuple[float, float]:
    """Approximate real/reactive flow on a line from bus power injections is
    not directly exposed as a per-branch algebraic var in this model config,
    so we report the line's connectivity-weighted average bus power flow
    proxy. For the dashboard this is used only as a qualitative flow
    indicator (line glow intensity), not an audited quantity."""
    try:
        i = ss.Line.idx.v.index(line_idx)
        u = ss.Line.u.v[i]
        b1 = ss.Line.bus1.v[i]
        b2 = ss.Line.bus2.v[i]
        bi1 = ss.Bus.idx.v.index(b1)
        bi2 = ss.Bus.idx.v.index(b2)
        v1, v2 = ss.Bus.v.v[bi1], ss.Bus.v.v[bi2]
        a1, a2 = ss.Bus.a.v[bi1], ss.Bus.a.v[bi2]
        x = max(ss.Line.x.v[i], 1e-6)
        p = (v1 * v2 / x) * math.sin(a1 - a2) * u
        q = 0.0
        return p, q
    except Exception:
        return 0.0, 0.0


def capture_frame(ss, t: float, f0_hz: float = 50.0, prev_freq_hz: float | None = None,
                   dt: float = 0.02, data_quality: str = "VALID") -> PmuFrame:
    """Read the current ANDES system state (after a TDS step to time t) and
    format it as a PmuFrame."""
    omega_avg = float(ss.GENROU.omega.v.mean())
    freq_hz = omega_avg * f0_hz
    rocof = 0.0 if prev_freq_hz is None else (freq_hz - prev_freq_hz) / dt

    bus_v, bus_ang = {}, {}
    for b in MONITORED_BUSES:
        i = ss.Bus.idx.v.index(b)
        bus_v[str(b)] = float(ss.Bus.v.v[i])
        bus_ang[str(b)] = float(math.degrees(ss.Bus.a.v[i]))

    branch_p, branch_q = {}, {}
    for ln in MONITORED_BRANCHES:
        p, q = _line_flow(ss, ln)
        branch_p[ln] = p
        branch_q[ln] = q

    gen_p, gen_q, gen_omega = {}, {}, {}
    for i, gidx in enumerate(ss.GENROU.idx.v):
        gen_p[str(gidx)] = float(ss.GENROU.Pe.v[i])
        gen_q[str(gidx)] = float(ss.GENROU.Qe.v[i])
        gen_omega[str(gidx)] = float(ss.GENROU.omega.v[i])

    return PmuFrame(
        t=t, freq_hz=freq_hz, rocof_hz_s=rocof,
        bus_v_pu=bus_v, bus_angle_deg=bus_ang,
        branch_p_pu=branch_p, branch_q_pu=branch_q,
        gen_p_pu=gen_p, gen_q_pu=gen_q, gen_omega_pu=gen_omega,
        data_quality=data_quality,
        status_flags={"islanded": False},
    )
