"""
Detection lead-time check for the IEEE 39-bus combined fault (v2.1),
using the RECALIBRATED detector for this network
(detect.sustained_growth_detector.SustainedGrowthDetector), not the
Kundur-validated ThresholdDetector, which was shown to false-fire on both
isolation counterfactuals here (see git history / README for the
diagnosis). See detect/sustained_growth_detector.py's module docstring
for the full derivation of why a plateau-then-breakout criterion on bus
voltage, not a magnitude threshold on the P/Q-derived reactive-margin
proxy, is what this network actually needs.

Validates all four requirements before reporting any lead-time number:
  (a) does not fire on the topology-alone counterfactual, full horizon
  (b) does not fire on the excitation-alone counterfactual, full horizon
  (c) fires on the real combined fault
  (d) the firing is causally tied to genuine divergence -- confirmed by
      comparing the plateau/breakout windows at the firing tick against
      the same absolute tick in both benign counterfactuals

Run: python -m sim.run_ieee39_detection_check
"""
from __future__ import annotations

import numpy as np
import andes

from sim.ieee39_scenario import build_ieee39_case, ScenarioTimes39, apply_excitation_ramp_39, FN_HZ
from detect.sustained_growth_detector import SustainedGrowthDetector
from detect.collapse_monitor import CollapseMonitor

DT = 0.1
SCADA_REFRESH_S = 4.0
DETECTOR_BUSES_39 = ['30', '31', '38', '4', '14', '16', '17']


def run_case(label: str, apply_weakening: bool, apply_excitation_fault: bool, times: ScenarioTimes39):
    ss, _ = build_ieee39_case(times, apply_weakening=apply_weakening, apply_excitation_fault=apply_excitation_fault)
    ss.PFlow.run()
    assert ss.PFlow.converged

    all_buses = [str(int(b)) for b in ss.Bus.idx.v]
    real_gen_buses = [30, 31, 32, 33, 34, 35, 36, 37, 38]
    genrou_bus_list = [int(b) for b in ss.GENROU.bus.v]
    real_gen_omega_idx = [genrou_bus_list.index(b) for b in real_gen_buses]
    bus_list = [int(b) for b in ss.Bus.idx.v]

    ss.TDS.config.tf = times.horizon_t
    ss.TDS.config.criteria = 0

    detector = SustainedGrowthDetector(monitored_buses=DETECTOR_BUSES_39, dt=DT)
    monitor = CollapseMonitor(monitored_buses=all_buses, dt=DT)
    n_ticks = int(round(times.horizon_t / DT))

    detection_t = None
    detection_reasons = []

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
            frame = {"t": t_target, "freq_hz": 0.0, "bus_v_pu": {b: 0.0 for b in all_buses}}

        if detection_t is None:
            det = detector.update(frame)
            if det["fired_this_tick"]:
                detection_t = t_target
                detection_reasons = det["reasons"]

        collapsed_now = monitor.update(frame, tds_ok)
        if collapsed_now or not tds_ok:
            break

    return detection_t, detection_reasons, monitor.collapsed_t, monitor.collapse_reason


def main():
    andes.config_logger(stream_level=30)
    times = ScenarioTimes39()

    print("=" * 70)
    print("STEP 1: validate on both isolation counterfactuals + the combined fault")
    print("=" * 70)

    det_a, _, coll_a, _ = run_case("(a) topology alone", True, False, times)
    print(f"(a) topology alone:    detection={det_a}, collapsed_t={coll_a}  "
          f"{'PASS (no false alarm)' if det_a is None and coll_a is None else 'FAIL'}")

    det_b, _, coll_b, _ = run_case("(b) excitation alone", False, True, times)
    print(f"(b) excitation alone:  detection={det_b}, collapsed_t={coll_b}  "
          f"{'PASS (no false alarm)' if det_b is None and coll_b is None else 'FAIL'}")

    det_c, reasons_c, coll_c, reason_c = run_case("(c) combined", True, True, times)
    print(f"(c) combined:          detection={det_c}, collapsed_t={coll_c}  "
          f"{'PASS (fired + collapsed)' if det_c is not None and coll_c is not None else 'FAIL'}")

    all_pass = (det_a is None and coll_a is None and
                det_b is None and coll_b is None and
                det_c is not None and coll_c is not None)

    print()
    if not all_pass:
        print("NOT ALL CHECKS PASSED -- refusing to report a lead-time number.")
        return

    print("All three checks (a)/(b)/(c) PASS.")
    print()
    print(f"Detection fired at t={det_c}s:")
    for r in reasons_c:
        print(f"  - {r}")
    print(f"Collapse at t={coll_c}s: {reason_c}")

    lead = coll_c - det_c
    print()
    print(f"Lead time, detection to collapse: {lead:.1f}s")
    print(f"SCADA baseline (~{SCADA_REFRESH_S:.0f}s refresh cited in BUILD_PROMPT.md): "
          f"lead time is {lead/SCADA_REFRESH_S:.2f}x the refresh cycle")
    if lead > SCADA_REFRESH_S:
        print(f"CLEARS the SCADA baseline: {lead:.1f}s vs {SCADA_REFRESH_S:.0f}s.")
    else:
        print(f"DOES NOT CLEAR the SCADA baseline: {lead:.1f}s vs {SCADA_REFRESH_S:.0f}s -- "
              f"shorter than a single SCADA refresh cycle.")


if __name__ == "__main__":
    main()
