"""
IEEE 39-bus equivalent of Phase 1: a genuinely zero-disturbance baseline.

Unlike the Kundur case, this requires no explicit disabling step -- the
MATPOWER-imported case39.m carries no Toggle devices at all (confirmed:
ss.Toggle.n == 0). Running it completely as-imported, with only the
minimal GENCLS dynamics added (sim.ieee39_system), IS the zero-disturbance
run. This script's job is just to prove that explicitly, with numbers.

Run: python -m sim.ieee39_phase1_baseline
"""
from __future__ import annotations

from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.ieee39_system import load_case39_matpower, FN_HZ

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def main():
    andes.config_logger(stream_level=30)

    ss = load_case39_matpower(with_dynamics=True)
    assert ss.Toggle.n == 0, "expected zero Toggle devices in the raw MATPOWER import"

    ss.PFlow.run()
    assert ss.PFlow.converged

    tf = 30.0
    ss.TDS.config.tf = tf
    ss.TDS.run()
    assert ss.TDS.converged

    t = ss.dae.ts.t
    x = ss.dae.ts.x
    y = ss.dae.ts.y
    omega_addr = ss.GENCLS.omega.a
    delta_addr = ss.GENCLS.delta.a
    gen_names = list(ss.GENCLS.idx.v)

    freq_hz = x[:, omega_addr].mean(axis=1) * FN_HZ

    bus_ids = [30, 31, 32, 33, 34, 35, 36, 37, 38, 39]
    bus_v = {}
    for b in bus_ids:
        i = ss.Bus.idx.v.index(b)
        bus_v[b] = y[:, ss.Bus.v.a[i]]

    max_freq_dev = float(np.max(np.abs(freq_hz - FN_HZ)))
    max_v_dev = max(float(np.max(np.abs(bus_v[b] - bus_v[b][0]))) for b in bus_ids)
    max_angle_dev_deg = float(np.max(np.abs(np.degrees(x[:, delta_addr] - x[0, delta_addr]))))

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    axes[0].plot(t, freq_hz, color="#2a6", linewidth=1.4)
    axes[0].set_ylabel(f"System frequency (Hz, {FN_HZ:.0f} Hz nominal)")
    axes[0].set_ylim(FN_HZ - 0.1, FN_HZ + 0.1)
    axes[0].grid(True, alpha=0.3)

    for b in [30, 34, 39]:
        axes[1].plot(t, bus_v[b], label=f"Bus {b}", linewidth=1.2)
    axes[1].set_ylabel("Generator bus voltage (p.u.)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    for i, name in enumerate(gen_names):
        axes[2].plot(t, np.degrees(x[:, delta_addr[i]]), linewidth=1.0)
    axes[2].set_ylabel("Rotor angle, all 10 gens (deg)")
    axes[2].set_xlabel("Time (s)")
    axes[2].grid(True, alpha=0.3)

    fig.suptitle("IEEE 39-bus (MATPOWER case39.m + GENCLS) -- zero-disturbance baseline: flat, as required")
    fig.tight_layout()
    out_path = REPORTS_DIR / "ieee39_phase1_baseline.png"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)

    print("PFlow converged:", ss.PFlow.converged)
    print("TDS converged:", ss.TDS.converged)
    print("Toggle count in raw MATPOWER import:", ss.Toggle.n, "(no baked-in disturbance -- unlike Kundur)")
    print(f"Max frequency deviation from {FN_HZ:.0f} Hz over {tf:.0f}s: {max_freq_dev:.6f} Hz")
    print(f"Max generator-bus voltage deviation from t=0 value: {max_v_dev:.6f} p.u.")
    print(f"Max rotor angle deviation from t=0 value: {max_angle_dev_deg:.6f} deg")
    print("PASS: undisturbed time series is flat" if max_freq_dev < 0.01 and max_v_dev < 0.01
          else "FAIL: baseline is not flat")
    print("Plot saved to:", out_path)


if __name__ == "__main__":
    main()
