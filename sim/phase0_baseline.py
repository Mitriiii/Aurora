"""
Phase 0 acceptance check (see BUILD_PROMPT.md, Section 6): confirm the
toolchain works end to end on the *unmodified* ANDES Kundur two-area,
four-machine benchmark case -- no custom scenario, no fault injection, no
detector. Just: load the case, solve the power flow, run a time-domain
simulation, and plot rotor speed (omega) to show the classic inter-area
oscillation the benchmark exists to demonstrate.

Run: python -m sim.phase0_baseline
"""
from __future__ import annotations

from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def main():
    andes.config_logger(stream_level=20)

    ss = andes.load(andes.get_case('kundur/kundur_full.xlsx'), no_output=True)

    ss.PFlow.run()
    assert ss.PFlow.converged, "power flow did not converge"

    ss.TDS.config.tf = 30
    ss.TDS.run()
    assert ss.TDS.converged, "time-domain simulation did not converge"

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "phase0_kundur_omega.png"

    omega_addr = ss.GENROU.omega.a
    gen_names = list(ss.GENROU.idx.v)
    t = ss.dae.ts.t
    x = ss.dae.ts.x

    fig, ax = plt.subplots(figsize=(9, 5))
    for addr, name in zip(omega_addr, gen_names):
        ax.plot(t, x[:, addr], label=f"GENROU {name}", linewidth=1.4)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Rotor speed, omega (p.u.)")
    ax.set_title("Phase 0 — unmodified ANDES Kundur two-area system: rotor speed oscillation")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)

    print("PFlow converged:", ss.PFlow.converged)
    print("TDS converged:", ss.TDS.converged)
    print("Buses:", ss.Bus.n, "Generators:", ss.GENROU.n)
    print("Plot saved to:", out_path)


if __name__ == "__main__":
    main()
