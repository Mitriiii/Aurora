"""
Phase 2/3/4 audit evidence: turns data/runs/latest.json into plots, not just
console numbers. Run after sim.run_scenario.

Produces:
  reports/phase2_3_uncorrected.png  -- voltage/frequency/margin vs time,
      with the detection point, each trip, and collapse all marked
      (Phase 2: qualitative fault signature; Phase 3: detection lead time)
  reports/phase4_comparison.png     -- uncorrected vs corrected frequency
      and voltage overlaid (Phase 4: genuine counterfactual survival)
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def _series(frames, key, sub=None):
    if sub is None:
        return np.array([f[key] for f in frames])
    return np.array([f[key].get(sub, np.nan) if f[key] else np.nan for f in frames])


def main():
    with open(RUNS_DIR / "latest.json") as f:
        result = json.load(f)

    u = result["uncorrected"]
    c = result["corrected"]
    times = result["scenario_times"]
    tanphi = np.tan(np.arccos(result["pf_limit"]))

    t_u = _series(u["frames"], "t")
    v8_u = _series(u["frames"], "bus_v_pu", "8")
    freq_u = _series(u["frames"], "freq_hz")

    gen_p_u = [f["gen_p_pu"] for f in u["frames"]]
    gen_q_u = [f["gen_q_pu"] for f in u["frames"]]
    margin_u = np.array([
        min((abs(p) * tanphi - abs(q) for p, q in zip(gp.values(), gq.values())), default=np.nan)
        if gp else np.nan
        for gp, gq in zip(gen_p_u, gen_q_u)
    ])

    # ---------- Phase 2/3 plot ----------
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)

    axes[0].plot(t_u, v8_u, color="#c44", linewidth=1.2)
    axes[0].set_ylabel("Bus 8 voltage (p.u.)")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(t_u, freq_u, color="#26a", linewidth=1.2)
    axes[1].set_ylabel("Frequency (Hz)")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(t_u, margin_u, color="#2a6", linewidth=1.2)
    axes[2].axhline(0, color="#888", linewidth=0.8, linestyle=":")
    axes[2].set_ylabel("Min reactive margin (p.u.)")
    axes[2].set_xlabel("Time (s)")
    axes[2].grid(True, alpha=0.3)

    for ax in axes:
        ax.axvline(times["surge_on_t"], color="orange", linestyle="--", linewidth=1, label="surge onset")
        if u["detection_t"] is not None:
            ax.axvline(u["detection_t"], color="red", linestyle="-", linewidth=1.4, label="AURORA detection")
        ax.axvline(times["trip_1_t"], color="black", linestyle="--", linewidth=1, label="trip 1")
        ax.axvline(times["trip_2_t"], color="black", linestyle="--", linewidth=1)
        ax.axvline(times["trip_3_t"], color="black", linestyle="--", linewidth=1)
        if u["collapse_t"] is not None:
            ax.axvline(u["collapse_t"], color="purple", linestyle="-", linewidth=1.4, label="collapse")

    axes[0].legend(loc="upper right", fontsize=8)
    fig.suptitle(
        f"Phase 2/3 — uncorrected cascade\n"
        f"detection t={u['detection_t']}s | lead to trip 1: {u['lead_time_to_first_trip_s']}s "
        f"| lead to collapse: {u['lead_time_to_collapse_s']}s | collapse t={u['collapse_t']}s"
    )
    fig.tight_layout()
    out1 = REPORTS_DIR / "phase2_3_uncorrected.png"
    fig.savefig(out1, dpi=150)

    # ---------- Phase 4 comparison plot ----------
    if c is not None:
        t_c = _series(c["frames"], "t")
        v8_c = _series(c["frames"], "bus_v_pu", "8")
        freq_c = _series(c["frames"], "freq_hz")

        fig2, axes2 = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
        axes2[0].plot(t_u, v8_u, color="#c44", label="Uncorrected (what happened)", linewidth=1.2)
        axes2[0].plot(t_c, v8_c, color="#2a6", label="AURORA-corrected", linewidth=1.2)
        axes2[0].set_ylabel("Bus 8 voltage (p.u.)")
        axes2[0].legend()
        axes2[0].grid(True, alpha=0.3)

        axes2[1].plot(t_u, freq_u, color="#c44", label="Uncorrected", linewidth=1.2)
        axes2[1].plot(t_c, freq_c, color="#2a6", label="AURORA-corrected", linewidth=1.2)
        axes2[1].set_ylabel("Frequency (Hz)")
        axes2[1].set_xlabel("Time (s)")
        axes2[1].legend()
        axes2[1].grid(True, alpha=0.3)

        for ax in axes2:
            if u["detection_t"] is not None:
                ax.axvline(u["detection_t"], color="red", linestyle="-", linewidth=1.2, alpha=0.6)
            if u["collapse_t"] is not None:
                ax.axvline(u["collapse_t"], color="purple", linestyle="--", linewidth=1.2, alpha=0.6)

        fig2.suptitle(
            f"Phase 4 — genuine counterfactual: uncorrected collapses at t={u['collapse_t']}s, "
            f"corrected collapse: {c['collapse_t']}"
        )
        fig2.tight_layout()
        out2 = REPORTS_DIR / "phase4_comparison.png"
        fig2.savefig(out2, dpi=150)
        print("Saved:", out2)

    print("Saved:", out1)
    print(f"detection_t={u['detection_t']} lead_to_trip1={u['lead_time_to_first_trip_s']} "
          f"lead_to_collapse={u['lead_time_to_collapse_s']} collapse_t={u['collapse_t']} "
          f"corrected_collapse_t={c['collapse_t'] if c else None}")


if __name__ == "__main__":
    main()
