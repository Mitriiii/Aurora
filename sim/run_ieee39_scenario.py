"""
Runs the ported fault mechanism on the IEEE 39-bus network (one step: get
it running and report what happens). Feeds ONLY detect.collapse_monitor.
CollapseMonitor -- the early-warning ThresholdDetector and the benign
scenario are explicitly not touched this round, per instruction.

Run: python -m sim.run_ieee39_scenario
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.ieee39_scenario import (
    build_uncorrected_39, ScenarioTimes39, apply_excitation_ramp_39,
    FAULT_GENS_39, WEAKENING_LINES_39, EXCITATION_RAMP_DURATION_S, FN_HZ,
)
from detect.collapse_monitor import CollapseMonitor

DT = 0.1
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
TRACKED_BUSES = ['4', '14', '16', '17', '2', '6', '29', '30', '31', '38']


def main():
    andes.config_logger(stream_level=30)
    times = ScenarioTimes39()

    print(f"Fault generators (bus): {FAULT_GENS_39}")
    print(f"Ramp duration (derived, 3x mean Td10): {EXCITATION_RAMP_DURATION_S:.2f}s")
    print(f"Weakening lines (confirmed connected, all 39 buses reachable): {WEAKENING_LINES_39}")
    print(f"Contingency/ramp start: t={times.contingency_t}s, horizon: {times.horizon_t}s")
    print()

    ss, _ = build_uncorrected_39(times)
    ss.PFlow.run()
    assert ss.PFlow.converged, "power flow did not converge"

    all_buses = [str(int(b)) for b in ss.Bus.idx.v]
    real_gen_buses = [30, 31, 32, 33, 34, 35, 36, 37, 38]  # excludes bus 39 (interconnection equivalent)
    genrou_bus_list = [int(b) for b in ss.GENROU.bus.v]
    real_gen_omega_idx = [genrou_bus_list.index(b) for b in real_gen_buses]
    bus_list = [int(b) for b in ss.Bus.idx.v]

    ss.TDS.config.tf = times.horizon_t
    ss.TDS.config.criteria = 0

    monitor = CollapseMonitor(monitored_buses=all_buses, dt=DT)
    n_ticks = int(round(times.horizon_t / DT))

    t_wall0 = time.time()
    t_hist, freq_hist, v_hist = [], [], {b: [] for b in TRACKED_BUSES}
    vrmin_hist = []
    collapsed = False
    max_v_global, max_v_global_bus = 0.0, None

    for i in range(1, n_ticks + 1):
        t_target = round(i * DT, 6)
        apply_excitation_ramp_39(ss, t_target, times)
        ss.TDS.config.tf = t_target
        ss.TDS.run()
        tds_ok = ss.TDS.converged

        if tds_ok:
            omega_mean = float(np.mean([ss.GENROU.omega.v[j] for j in real_gen_omega_idx]))
            freq_hz = omega_mean * FN_HZ
            frame_v = {str(b): float(ss.Bus.v.v[k]) for k, b in enumerate(bus_list)}
            frame = {"t": t_target, "freq_hz": freq_hz, "bus_v_pu": frame_v}
            for b, v in frame_v.items():
                if v > max_v_global:
                    max_v_global, max_v_global_bus = v, b
        else:
            freq_hz = 0.0
            frame = {"t": t_target, "freq_hz": 0.0, "bus_v_pu": {b: 0.0 for b in all_buses}}

        collapsed_now = monitor.update(frame, tds_ok)

        t_hist.append(t_target)
        freq_hist.append(freq_hz)
        for b in v_hist:
            v_hist[b].append(frame["bus_v_pu"].get(b, np.nan))
        vrmin_hist.append([ss.IEEEX1.VRMIN.v[ix] for ix in ss._excitation_fault_idx_39])

        if collapsed_now:
            collapsed = True
            print(f"COLLAPSE at t={monitor.collapsed_t}s: {monitor.collapse_reason}")
            break
        if not tds_ok:
            break

    wall_s = time.time() - t_wall0
    print(f"\nWall time: {wall_s:.1f}s, reached t={t_hist[-1] if t_hist else 0:.1f}s of {times.horizon_t}s requested")

    if not collapsed:
        print("NO COLLAPSE within the horizon under the physics-derived CollapseMonitor criteria "
              "(sustained frequency/voltage protective-threshold violation).")
        print(f"Final frequency: {freq_hist[-1]:.4f} Hz")
        print(f"Final bus voltages (spot check): " +
              ", ".join(f"bus{b}={v_hist[b][-1]:.4f}" for b in v_hist))
        print(f"Max voltage seen across ALL 39 buses: {max_v_global:.4f} p.u. at bus {max_v_global_bus} "
              f"({100*max_v_global/1.5:.1f}% of the 1.5 p.u. collapse threshold)")

    # ---------- Plot ----------
    t_arr = np.array(t_hist)
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)

    for b in TRACKED_BUSES:
        axes[0].plot(t_arr, v_hist[b], label=f"Bus {b}", linewidth=1.0)
    axes[0].set_ylabel("Bus voltage (p.u.)")
    axes[0].legend(fontsize=8)
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(t_arr, freq_hist, color="#26a", linewidth=1.2)
    axes[1].set_ylabel(f"System frequency (Hz, {FN_HZ:.0f} nominal, real gens only)")
    axes[1].grid(True, alpha=0.3)

    vrmin_arr = np.array(vrmin_hist)
    for i, bus in enumerate(FAULT_GENS_39):
        axes[2].plot(t_arr, vrmin_arr[:, i], label=f"VRMIN gen@bus{bus}", linewidth=1.2)
    axes[2].set_ylabel("VRMIN (p.u.)")
    axes[2].set_xlabel("Time (s)")
    axes[2].legend(fontsize=8)
    axes[2].grid(True, alpha=0.3)

    for ax in axes:
        ax.axvline(times.contingency_t, color="orange", linestyle="--", linewidth=1)
        if collapsed:
            ax.axvline(monitor.collapsed_t, color="purple", linewidth=1.4)

    title = f"IEEE 39-bus fault mechanism v2: corridor weakening (Line_9+Line_26, confirmed connected) + VRMIN ramp on gens 30/31/38\n"
    title += f"COLLAPSE at t={monitor.collapsed_t:.1f}s ({monitor.collapse_reason})" if collapsed else "NO COLLAPSE within horizon"
    fig.suptitle(title)
    fig.tight_layout()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "ieee39_fault_mechanism.png"
    fig.savefig(out_path, dpi=150)
    print(f"\nPlot saved to: {out_path}")


if __name__ == "__main__":
    main()
