"""
Isolation counterfactuals for the IEEE 39-bus fault mechanism v2 -- the
same discipline applied to Kundur (and to v1 of this mechanism, which
failed this exact check) before any combined fault is trusted: run each
half alone, and confirm NEITHER collapses the system by itself. If either
does, the combination doesn't mean what it's supposed to mean, and that
has to be reported plainly, not tuned away before reporting.

(a) Corridor weakening (Line_9 + Line_26 -- confirmed connected by
    exhaustive BFS, not an island) alone, VRMIN held at its healthy
    baseline on all three target generators (30, 31, 38) -- the run loop
    simply never calls apply_excitation_ramp_39.
(b) VRMIN ramp alone on generators 30, 31, 38 -- network fully intact, no
    line trips at all.

Run: python -m sim.run_ieee39_isolation_checks
"""
from __future__ import annotations

from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.ieee39_scenario import (
    build_ieee39_case, ScenarioTimes39, apply_excitation_ramp_39,
    FAULT_GENS_39, WEAKENING_LINES_39, FN_HZ,
)
from detect.collapse_monitor import CollapseMonitor

DT = 0.1
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
TRACKED_BUSES = ['4', '14', '16', '17', '2', '6', '29']  # corridor endpoints + fault-gen attachment buses


def run_case(label: str, apply_weakening: bool, apply_excitation_fault: bool, times: ScenarioTimes39):
    ss, _ = build_ieee39_case(times, apply_weakening=apply_weakening, apply_excitation_fault=apply_excitation_fault)
    ss.PFlow.run()
    assert ss.PFlow.converged, f"[{label}] power flow did not converge"

    all_buses = [str(int(b)) for b in ss.Bus.idx.v]
    real_gen_buses = [30, 31, 32, 33, 34, 35, 36, 37, 38]
    genrou_bus_list = [int(b) for b in ss.GENROU.bus.v]
    real_gen_omega_idx = [genrou_bus_list.index(b) for b in real_gen_buses]
    bus_list = [int(b) for b in ss.Bus.idx.v]

    ss.TDS.config.tf = times.horizon_t
    ss.TDS.config.criteria = 0

    monitor = CollapseMonitor(monitored_buses=all_buses, dt=DT)
    n_ticks = int(round(times.horizon_t / DT))

    t_hist, freq_hist = [], []
    v_track = {b: [] for b in TRACKED_BUSES}

    for i in range(1, n_ticks + 1):
        t_target = round(i * DT, 6)
        if apply_excitation_fault:
            apply_excitation_ramp_39(ss, t_target, times)
        ss.TDS.config.tf = t_target
        ss.TDS.run()
        tds_ok = ss.TDS.converged

        if tds_ok:
            omega_mean = float(np.mean([ss.GENROU.omega.v[j] for j in real_gen_omega_idx]))
            freq_hz = omega_mean * FN_HZ
            frame_v = {str(b): float(ss.Bus.v.v[k]) for k, b in enumerate(bus_list)}
            frame = {"t": t_target, "freq_hz": freq_hz, "bus_v_pu": frame_v}
        else:
            freq_hz = 0.0
            frame = {"t": t_target, "freq_hz": 0.0, "bus_v_pu": {b: 0.0 for b in all_buses}}

        collapsed_now = monitor.update(frame, tds_ok)
        t_hist.append(t_target)
        freq_hist.append(freq_hz)
        for b in v_track:
            v_track[b].append(frame["bus_v_pu"].get(b, np.nan))

        if collapsed_now or not tds_ok:
            break

    print(f"=== {label} ===")
    if monitor.collapsed:
        print(f"COLLAPSED at t={monitor.collapsed_t}s: {monitor.collapse_reason}")
    else:
        print(f"NO COLLAPSE over the full {times.horizon_t:.0f}s horizon.")
        print(f"  Final frequency: {freq_hist[-1]:.4f} Hz")
        print(f"  Final voltages: " + ", ".join(f"bus{b}={v_track[b][-1]:.4f}" for b in v_track))
        print(f"  Max |freq-{FN_HZ:.0f}| over run: {max(abs(f-FN_HZ) for f in freq_hist):.4f} Hz")
        print(f"  Max voltage seen (any tracked bus): {max(max(v) for v in v_track.values()):.4f} p.u.")
    print()

    return dict(label=label, t=np.array(t_hist), freq=np.array(freq_hist), v=v_track,
                collapsed=monitor.collapsed, collapsed_t=monitor.collapsed_t,
                collapse_reason=monitor.collapse_reason)


def main():
    andes.config_logger(stream_level=30)
    times = ScenarioTimes39()

    print(f"Weakening lines (confirmed connected, all 39 buses reachable by exhaustive BFS): {WEAKENING_LINES_39}")
    print(f"Fault generators: {FAULT_GENS_39} (not adjacent to the weakened corridor, edge-connectivity 2)")
    print(f"Contingency/ramp start: t={times.contingency_t}s, horizon: {times.horizon_t}s\n")

    result_a = run_case("(a) Corridor weakening ALONE, VRMIN held healthy", apply_weakening=True,
                         apply_excitation_fault=False, times=times)
    result_b = run_case("(b) VRMIN ramp ALONE, network fully intact", apply_weakening=False,
                         apply_excitation_fault=True, times=times)

    print("=== Summary ===")
    for r in (result_a, result_b):
        verdict = f"COLLAPSED at t={r['collapsed_t']}s" if r['collapsed'] else "did not collapse"
        print(f"{r['label']}: {verdict}")
    both_clean = not result_a['collapsed'] and not result_b['collapsed']
    if both_clean:
        print("\nBoth isolation counterfactuals PASS (neither collapses alone) -- a combined-fault "
              "result, if run next, would mean what it's supposed to mean: it takes both the "
              "corridor weakening AND the excitation ramp together.")
    else:
        print("\nAT LEAST ONE COUNTERFACTUAL COLLAPSED ALONE -- the compound fault does not "
              "demonstrate what it was meant to. Reporting as-is; the combination needs rework.")

    # ---------- Plot ----------
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex='col')
    for col, r in enumerate((result_a, result_b)):
        ax_v, ax_f = axes[0, col], axes[1, col]
        for b in TRACKED_BUSES:
            ax_v.plot(r['t'], r['v'][b], label=f"Bus {b}", linewidth=1.0)
        ax_v.set_title(r['label'], fontsize=10)
        ax_v.set_ylabel("Bus voltage (p.u.)")
        ax_v.legend(fontsize=6, ncol=2)
        ax_v.grid(True, alpha=0.3)
        ax_v.axvline(times.contingency_t, color="orange", linestyle="--", linewidth=1)
        if r['collapsed']:
            ax_v.axvline(r['collapsed_t'], color="purple", linewidth=1.4)

        ax_f.plot(r['t'], r['freq'], color="#26a", linewidth=1.2)
        ax_f.set_ylabel(f"Frequency (Hz, {FN_HZ:.0f} nominal)")
        ax_f.set_xlabel("Time (s)")
        ax_f.grid(True, alpha=0.3)
        ax_f.axvline(times.contingency_t, color="orange", linestyle="--", linewidth=1)
        if r['collapsed']:
            ax_f.axvline(r['collapsed_t'], color="purple", linewidth=1.4)

    fig.suptitle("IEEE 39-bus isolation counterfactuals v2: corridor weakening vs. excitation ramp, each alone")
    fig.tight_layout()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "ieee39_isolation_checks.png"
    fig.savefig(out_path, dpi=150)
    print(f"\nPlot saved to: {out_path}")


if __name__ == "__main__":
    main()
