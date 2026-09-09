"""
Detection lead-time check for the IEEE 39-bus combined fault (v2.1,
verified marginal-but-insufficient on both halves in isolation -- see
sim/ieee39_scenario.py and the isolation-counterfactual results).

Runs the SAME detect.threshold_detector.ThresholdDetector validated on
Kundur, unmodified, against this network's combined fault, tick-by-tick,
alongside the same detect.collapse_monitor.CollapseMonitor used throughout
this network's work. Reports first-detection time, lead time to the actual
collapse, and both compared against the ~4s SCADA refresh baseline cited
in BUILD_PROMPT.md.

Run: python -m sim.run_ieee39_detection_check
"""
from __future__ import annotations

from pathlib import Path

import andes
import numpy as np

from sim.ieee39_scenario import build_uncorrected_39, ScenarioTimes39, apply_excitation_ramp_39, FN_HZ
from detect.threshold_detector import ThresholdDetector
from detect.collapse_monitor import CollapseMonitor

DT = 0.1
SCADA_REFRESH_S = 4.0

# Where the fault signal actually shows up: the fault-generator buses
# (30, 31, 38) plus the weakened corridor's endpoints (4, 14, 16, 17) --
# analogous to Kundur's DETECTOR_BUSES sitting near its tie/surge region.
DETECTOR_BUSES_39 = ['30', '31', '38', '4', '14', '16', '17']


def main():
    andes.config_logger(stream_level=30)
    times = ScenarioTimes39()

    ss, _ = build_uncorrected_39(times)
    ss.PFlow.run()
    assert ss.PFlow.converged

    all_buses = [str(int(b)) for b in ss.Bus.idx.v]
    real_gen_buses = [30, 31, 32, 33, 34, 35, 36, 37, 38]
    genrou_bus_list = [int(b) for b in ss.GENROU.bus.v]
    genrou_idx_list = list(ss.GENROU.idx.v)
    real_gen_omega_idx = [genrou_bus_list.index(b) for b in real_gen_buses]
    bus_list = [int(b) for b in ss.Bus.idx.v]

    ss.TDS.config.tf = times.horizon_t
    ss.TDS.config.criteria = 0

    detector = ThresholdDetector(monitored_buses=DETECTOR_BUSES_39, dt=DT)
    monitor = CollapseMonitor(monitored_buses=all_buses, dt=DT)
    n_ticks = int(round(times.horizon_t / DT))

    detection_t = None
    detection_reasons = []

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
            gen_p = {genrou_idx_list[j]: float(ss.GENROU.Pe.v[j]) for j in range(len(genrou_idx_list))}
            gen_q = {genrou_idx_list[j]: float(ss.GENROU.Qe.v[j]) for j in range(len(genrou_idx_list))}
            frame = {"t": t_target, "freq_hz": freq_hz, "bus_v_pu": frame_v,
                     "gen_p_pu": gen_p, "gen_q_pu": gen_q}
        else:
            frame = {"t": t_target, "freq_hz": 0.0, "bus_v_pu": {b: 0.0 for b in all_buses},
                      "gen_p_pu": {}, "gen_q_pu": {}}

        if detection_t is None:
            det = detector.update(frame)
            if det["fired_this_tick"]:
                detection_t = t_target
                detection_reasons = det["reasons"]

        collapsed_now = monitor.update(frame, tds_ok)

        if collapsed_now or not tds_ok:
            break

    print("=" * 70)
    print("IEEE 39-BUS DETECTION LEAD-TIME CHECK")
    print("=" * 70)
    print(f"Detector buses: {DETECTOR_BUSES_39}")
    print(f"Ramp completes: t~{times.contingency_t + 21.55:.1f}s (contingency_t={times.contingency_t}s + ramp 21.55s)")
    print()

    if detection_t is not None:
        print(f"Detection fired at t={detection_t}s")
        for r in detection_reasons:
            print(f"  - {r}")
    else:
        print("Detector NEVER FIRED before the run ended.")

    print()
    if monitor.collapsed:
        print(f"Collapse at t={monitor.collapsed_t}s: {monitor.collapse_reason}")
    else:
        print("No collapse occurred in this run (unexpected -- check scenario state).")

    print()
    if detection_t is not None and monitor.collapsed_t is not None:
        lead_to_collapse = monitor.collapsed_t - detection_t
        print(f"Lead time, detection to collapse: {lead_to_collapse:.1f}s")
        print(f"SCADA baseline (~{SCADA_REFRESH_S:.0f}s refresh cited in BUILD_PROMPT.md): "
              f"lead time is {lead_to_collapse/SCADA_REFRESH_S:.1f}x the refresh cycle")
        if lead_to_collapse > SCADA_REFRESH_S:
            print(f"CLEARS the SCADA baseline comfortably: {lead_to_collapse:.1f}s vs {SCADA_REFRESH_S:.0f}s.")
        else:
            print(f"DOES NOT CLEAR the SCADA baseline: {lead_to_collapse:.1f}s vs {SCADA_REFRESH_S:.0f}s.")
    else:
        print("Cannot compute lead time -- detector did not fire and/or no collapse occurred.")


if __name__ == "__main__":
    main()
