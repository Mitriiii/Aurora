"""
IEEE 39-bus toolchain verification: NOT a scenario design choice.

The zero-disturbance baseline (ieee39_phase1_baseline.py) is flat by
construction -- it proves nothing about whether TDS actually produces
correct dynamic behavior on this new, larger network. This script applies
one arbitrary, generic, briefly-toggled line trip-and-reclose (Line_1,
picked only because it's first in the index -- no significance) purely to
confirm the solver responds sensibly: an oscillation appears, propagates,
and damps. This is the IEEE 39-bus equivalent of the Kundur Phase 0 plot,
which relied on that case's own stock disturbance -- there is no such
stock disturbance here, so a minimal generic one stands in for it.

This is explicitly NOT the fault mechanism. No calibrated fault magnitude,
tie-line choice, or generator selection here should be reused for that --
this kick is disposable, arbitrary, and exists only to prove the pipe
works end to end on the new network.

Run: python -m sim.ieee39_verification_kick
"""
from __future__ import annotations

from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.ieee39_system import load_case39_matpower, FN_HZ, CASE_PATH, GENERATOR_DYNAMICS_BY_BUS

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

KICK_LINE = "Line_1"
KICK_T = 2.0
KICK_DURATION = 0.06


def build_kicked_system():
    ss = andes.load(str(CASE_PATH), setup=False, no_output=True)
    gens = list(zip(ss.PV.idx.v, ss.PV.bus.v)) + list(zip(ss.Slack.idx.v, ss.Slack.bus.v))
    for gi, (gen_idx, bus) in enumerate(gens, start=1):
        params = GENERATOR_DYNAMICS_BY_BUS[int(bus)]
        ss.add('GENCLS', dict(
            idx=f'GENCLS_{gi}', bus=bus, gen=gen_idx,
            Sn=params['Sn'], Vn=345.0, fn=FN_HZ,
            D=params['D'], M=2 * params['H'],
            ra=params['ra'], xd1=params['xd1'],
        ))
    ss.add('Toggle', dict(model='Line', dev=KICK_LINE, t=KICK_T))
    ss.add('Toggle', dict(model='Line', dev=KICK_LINE, t=KICK_T + KICK_DURATION))
    ss.setup()
    return ss


def main():
    andes.config_logger(stream_level=30)
    ss = build_kicked_system()

    ss.PFlow.run()
    assert ss.PFlow.converged

    tf = 30.0
    ss.TDS.config.tf = tf
    ss.TDS.run()
    assert ss.TDS.converged, "verification kick failed to converge -- toolchain problem, investigate before anything else"

    t = ss.dae.ts.t
    x = ss.dae.ts.x
    omega_addr = ss.GENCLS.omega.a
    gen_names = list(ss.GENCLS.idx.v)

    fig, ax = plt.subplots(figsize=(9, 5))
    for i, name in enumerate(gen_names):
        ax.plot(t, x[:, omega_addr[i]], label=f"GENCLS {name}", linewidth=1.2)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Rotor speed, omega (p.u.)")
    ax.set_title(f"IEEE 39-bus toolchain verification: generic brief trip-reclose on {KICK_LINE} at t={KICK_T}s\n"
                 f"(NOT a scenario design choice -- arbitrary line, exists only to prove TDS works here)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    out_path = REPORTS_DIR / "ieee39_verification_kick.png"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)

    omega = x[:, omega_addr]
    print("PFlow converged:", ss.PFlow.converged)
    print("TDS converged:", ss.TDS.converged)
    print(f"Max omega deviation from 1.0 p.u. after kick: {np.max(np.abs(omega - 1.0)):.6f}")
    print(f"Final omega spread across 10 gens (max-min) at t={tf:.0f}s: {omega[-1].max() - omega[-1].min():.6e}")
    print("Plot saved to:", out_path)


if __name__ == "__main__":
    main()
