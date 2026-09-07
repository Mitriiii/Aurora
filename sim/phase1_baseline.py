"""
Phase 1 acceptance check (BUILD_PROMPT.md Section 6): "Wire the ANDES Kundur
two-area simulation into a script that runs a steady 30-second window with
no disturbance, streaming bus voltage, frequency, and generator rotor angles
to a simple logged output. Acceptance: a stable, undisturbed time series."

This uses AURORA's OWN wiring (sim.kundur_system.build_healthy) -- reduced
inertia and the governor fix applied, all the same devices present as in
every other scenario, but with zero disturbance toggled. If this isn't
flat, nothing built on top of it can be trusted.

Run: python -m sim.phase1_baseline
"""
from __future__ import annotations

from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.kundur_system import build_healthy, ScenarioTimes

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def main():
    andes.config_logger(stream_level=30)

    times = ScenarioTimes(horizon_t=30.0)
    ss, _ = build_healthy(times)

    ss.PFlow.run()
    assert ss.PFlow.converged, "power flow did not converge"

    ss.TDS.config.tf = times.horizon_t
    ss.TDS.run()
    assert ss.TDS.converged, "time-domain simulation did not converge"

    t = ss.dae.ts.t
    x = ss.dae.ts.x
    omega_addr = ss.GENROU.omega.a
    gen_names = list(ss.GENROU.idx.v)

    bus_ids = [7, 8, 9]
    bus_v = {b: [] for b in bus_ids}
    bus_a = {b: [] for b in bus_ids}
    # ss.dae.ts.y holds algebraic-variable time series (bus voltage/angle).
    y = ss.dae.ts.y
    for b in bus_ids:
        i = ss.Bus.idx.v.index(b)
        bus_v[b] = y[:, ss.Bus.v.a[i]]
        bus_a[b] = y[:, ss.Bus.a.a[i]]

    freq_hz = x[:, omega_addr].mean(axis=1) * 50.0

    # Numeric proof, not just a picture: how far did anything move from t=0?
    max_freq_dev = float(np.max(np.abs(freq_hz - 50.0)))
    max_v_dev = max(float(np.max(np.abs(bus_v[b] - bus_v[b][0]))) for b in bus_ids)
    max_angle_dev_deg = max(float(np.max(np.abs(np.degrees(bus_a[b] - bus_a[b][0])))) for b in bus_ids)

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)

    axes[0].plot(t, freq_hz, color="#2a6", linewidth=1.4)
    axes[0].set_ylabel("System frequency (Hz)")
    axes[0].set_ylim(49.9, 50.1)
    axes[0].grid(True, alpha=0.3)

    for b in bus_ids:
        axes[1].plot(t, bus_v[b], label=f"Bus {b}", linewidth=1.2)
    axes[1].set_ylabel("Bus voltage (p.u.)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    for i, name in enumerate(gen_names):
        axes[2].plot(t, np.degrees(x[:, ss.GENROU.delta.a[i]]), label=f"GENROU {name} rotor angle", linewidth=1.2)
    axes[2].set_ylabel("Rotor angle (deg)")
    axes[2].set_xlabel("Time (s)")
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    fig.suptitle("Phase 1 — zero-disturbance baseline (AURORA's own wiring): flat, as required")
    fig.tight_layout()
    out_path = REPORTS_DIR / "phase1_healthy_baseline.png"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)

    print("PFlow converged:", ss.PFlow.converged)
    print("TDS converged:", ss.TDS.converged)
    print(f"Max frequency deviation from 50.000 Hz over {times.horizon_t:.0f}s: {max_freq_dev:.6f} Hz")
    print(f"Max bus voltage deviation from t=0 value: {max_v_dev:.6f} p.u.")
    print(f"Max rotor angle deviation from t=0 value: {max_angle_dev_deg:.6f} deg")
    print(f"PASS: undisturbed time series is flat" if max_freq_dev < 0.01 and max_v_dev < 0.01
          else "FAIL: baseline is not flat -- something is perturbing the system with no fault scripted")
    print("Plot saved to:", out_path)


if __name__ == "__main__":
    main()
