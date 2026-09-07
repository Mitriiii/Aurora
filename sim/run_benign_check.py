"""
Detector false-alarm check (requested explicitly, not in the original
6-phase plan): runs the BENIGN, non-cascading control scenario --
sim.kundur_system.build_benign, modeling the real event's own two precursor
oscillations (~0.6 Hz at 12:03-12:07 and ~0.2 Hz at 12:16-12:22 CEST) that
wobbled and self-damped WITHOUT any reactive surge, generation trip, or
collapse -- through the exact same ThresholdDetector used on the cascade
scenario, with no threshold changes.

A detector that fires on this case is a false-alarm generator, not an
early-warning system. This script's job is to say plainly which one AURORA
currently is.

Run: python -m sim.run_benign_check
"""
from __future__ import annotations

import json
from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.kundur_system import build_benign, ScenarioTimes
from sim.pmu_stream import capture_frame, DETECTOR_BUSES
from detect.threshold_detector import ThresholdDetector, TAN_PHI_LIMIT

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
DT = 0.1


def main():
    andes.config_logger(stream_level=30)
    times = ScenarioTimes(horizon_t=60.0)

    ss, _ = build_benign(times)
    ss.PFlow.run()
    assert ss.PFlow.converged, "power flow did not converge"
    ss.TDS.config.tf = times.horizon_t
    ss.TDS.config.criteria = 0

    detector = ThresholdDetector(monitored_buses=[str(b) for b in DETECTOR_BUSES], dt=DT)

    n_ticks = int(round(times.horizon_t / DT))
    frames, det_log = [], []
    prev_freq = None
    collapsed = False

    for i in range(1, n_ticks + 1):
        t_target = round(i * DT, 6)
        ss.TDS.config.tf = t_target
        ss.TDS.run()
        if not ss.TDS.converged:
            collapsed = True
            print(f"UNEXPECTED: benign scenario failed to converge at t={t_target}s")
            break
        pf = capture_frame(ss, t_target, prev_freq_hz=prev_freq, dt=DT)
        prev_freq = pf.freq_hz
        frame = pf.to_dict()
        frames.append(frame)
        det = detector.update(frame)
        det_log.append(det)

    fired = detector.fired_t is not None

    # ---------- Evidence: plot ----------
    t = np.array([f["t"] for f in frames])
    v8 = np.array([f["bus_v_pu"]["8"] for f in frames])
    freq = np.array([f["freq_hz"] for f in frames])
    margin_min = np.array([
        min(abs(p) * TAN_PHI_LIMIT - abs(f["gen_q_pu"][g]) for g, p in f["gen_p_pu"].items())
        for f in frames
    ])

    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    axes[0].plot(t, v8, color="#26a", linewidth=1.2)
    axes[0].set_ylabel("Bus 8 voltage (p.u.)")
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(t, freq, color="#26a", linewidth=1.2)
    axes[1].set_ylabel("Frequency (Hz)")
    axes[1].grid(True, alpha=0.3)
    axes[2].plot(t, margin_min, color="#2a6", linewidth=1.2)
    axes[2].axhline(0, color="#888", linewidth=0.8, linestyle=":")
    axes[2].set_ylabel("Min reactive margin (p.u.)")
    axes[2].set_xlabel("Time (s)")
    axes[2].grid(True, alpha=0.3)

    for ax in axes:
        ax.axvline(times.line_kick_t, color="orange", linestyle="--", linewidth=1,
                   label="precursor 1 (~0.6Hz, real: 12:03-12:07)")
        ax.axvline(times.benign_second_kick_t, color="brown", linestyle="--", linewidth=1,
                   label="precursor 2 (~0.2Hz, real: 12:16-12:22)")
        if fired:
            ax.axvline(detector.fired_t, color="red", linestyle="-", linewidth=1.6, label="DETECTOR FIRED")

    axes[0].legend(loc="upper right", fontsize=8)
    verdict = "FALSE ALARM -- detector fired on a non-cascading, self-damping disturbance" if fired \
        else "CORRECTLY SILENT -- no false alarm on the benign case"
    fig.suptitle(f"Benign control scenario (two real precursor oscillations, no surge/trips/collapse)\n{verdict}")
    fig.tight_layout()
    out_path = REPORTS_DIR / "benign_control_check.png"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)

    print("=" * 70)
    print("BENIGN CONTROL SCENARIO -- DETECTOR FALSE-ALARM CHECK")
    print("=" * 70)
    print(f"Scenario converged throughout: {not collapsed}")
    print(f"Max |freq - 50| Hz over run: {np.max(np.abs(freq - 50)):.4f}")
    print(f"Max |v8 - 1.0| p.u. over run: {np.max(np.abs(v8 - 1.0)):.4f}")
    print(f"Min reactive margin ever seen: {np.min(margin_min):.3f} p.u.")
    print()
    if fired:
        print(f"RESULT: FALSE ALARM. Detector fired at t={detector.fired_t}s.")
        print("Reasons given:")
        for r in detector.fired_reasons:
            print(f"  - {r}")
    else:
        print("RESULT: Detector stayed SILENT for the full 60s run. No false alarm.")
    print(f"\nPlot saved to: {out_path}")

    with open(RUNS_DIR / "benign_check.json", "w") as f:
        json.dump({
            "fired": fired,
            "fired_t": detector.fired_t,
            "fired_reasons": detector.fired_reasons,
            "max_freq_dev_hz": float(np.max(np.abs(freq - 50))),
            "max_v8_dev_pu": float(np.max(np.abs(v8 - 1.0))),
            "min_margin_pu": float(np.min(margin_min)),
        }, f, indent=2)


if __name__ == "__main__":
    main()
