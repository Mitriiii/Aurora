"""
Phase 2 + Phase 3 + Phase 4 driver: runs the uncorrected timeline tick by
tick through the live detector (no hindsight), then builds and runs the
corrected branch using the moment the detector actually fired.

This is the honest core of the demo: both branches are genuine, independent
ANDES time-domain integrations from identical initial conditions. The
corrected branch's intervention time comes from the detector's real output
on the uncorrected run, not from foreknowledge of when the historical trips
happen to occur.

Usage:
    python -m sim.run_scenario                # runs and writes data/runs/*.json
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import andes

from sim.kundur_system import build_uncorrected, build_corrected, ScenarioTimes, PF_LIMIT
from sim.pmu_stream import capture_frame, MONITORED_BUSES, DETECTOR_BUSES, PMU_RATE_HZ
from detect.threshold_detector import ThresholdDetector

DT = 0.1  # tick resolution used for detection + streaming (10 Hz; PMU-record rate is separate)
RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"


def _run_branch(ss, times: ScenarioTimes, dt: float, detector: ThresholdDetector | None,
                 stop_after_collapse_s: float = 2.0):
    """Advance TDS tick-by-tick, capturing a PMU frame and (optionally)
    feeding the live detector at every step. Returns (frames, detector_log,
    collapse_t | None)."""
    ss.PFlow.run()
    ss.TDS.config.tf = times.horizon_t
    ss.TDS.config.criteria = 0

    n_ticks = int(round(times.horizon_t / dt))
    frames, detector_log = [], []
    prev_freq = None
    collapse_t = None

    for i in range(1, n_ticks + 1):
        t_target = round(i * dt, 6)
        ss.TDS.config.tf = t_target
        ss.TDS.run()

        if not ss.TDS.converged:
            collapse_t = collapse_t if collapse_t is not None else t_target
            collapsed_frame = {
                "t": t_target, "freq_hz": 0.0, "rocof_hz_s": 0.0,
                "bus_v_pu": {str(b): 0.0 for b in MONITORED_BUSES},
                "bus_angle_deg": {str(b): 0.0 for b in MONITORED_BUSES},
                "branch_p_pu": {}, "branch_q_pu": {},
                "gen_p_pu": {}, "gen_q_pu": {}, "gen_omega_pu": {},
                "data_quality": "MISSING",
                "status_flags": {"islanded": True, "collapsed": True},
            }
            # Solver has already declared collapse -- pad the remaining
            # buffer with the same frame instead of re-attempting the solve.
            n_remaining = min(n_ticks - i + 1, int(round(stop_after_collapse_s / dt)))
            for j in range(n_remaining):
                pad = dict(collapsed_frame)
                pad["t"] = round(t_target + j * dt, 3)
                frames.append(pad)
            break

        pf = capture_frame(ss, t_target, prev_freq_hz=prev_freq, dt=dt)
        prev_freq = pf.freq_hz
        frame = pf.to_dict()
        frames.append(frame)

        if detector is not None:
            det = detector.update(frame)
            detector_log.append(det)

    return frames, detector_log, collapse_t


def run_full_scenario(dt: float = DT) -> dict:
    andes.config_logger(stream_level=30)
    times = ScenarioTimes()

    t_wall0 = time.time()

    ss_u, _ = build_uncorrected(times)
    detector = ThresholdDetector(monitored_buses=[str(b) for b in DETECTOR_BUSES], dt=dt)
    frames_u, det_log, collapse_t = _run_branch(ss_u, times, dt, detector)

    detection_t = detector.fired_t
    detection_reasons = detector.fired_reasons
    lead_time_to_first_trip = None if detection_t is None else round(times.trip_1_t - detection_t, 2)
    lead_time_to_collapse = None if (detection_t is None or collapse_t is None) else round(collapse_t - detection_t, 2)

    uncorrected_result = {
        "branch": "uncorrected",
        "label": "What actually happened",
        "times": vars(times),
        "frames": frames_u,
        "detection_t": detection_t,
        "detection_reasons": detection_reasons,
        "collapse_t": collapse_t,
        "lead_time_to_first_trip_s": lead_time_to_first_trip,
        "lead_time_to_collapse_s": lead_time_to_collapse,
        "actions_taken": [],
    }

    corrected_result = None
    if detection_t is not None:
        ss_c, actions = build_corrected(times, detection_t)
        frames_c, _, collapse_t_c = _run_branch(ss_c, times, dt, detector=None)
        corrected_result = {
            "branch": "corrected",
            "label": "AURORA intervenes",
            "times": vars(times),
            "frames": frames_c,
            "detection_t": detection_t,
            "detection_reasons": detection_reasons,
            "collapse_t": collapse_t_c,
            "actions_taken": actions,
        }

    wall_s = round(time.time() - t_wall0, 2)

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dt": dt,
        "wall_time_s": wall_s,
        "scenario_times": vars(times),
        "pf_limit": PF_LIMIT,
        "uncorrected": uncorrected_result,
        "corrected": corrected_result,
    }
    return result


def main():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    result = run_full_scenario()

    with open(RUNS_DIR / "latest.json", "w") as f:
        json.dump(result, f)

    u = result["uncorrected"]
    print(f"Wall time: {result['wall_time_s']}s")
    print(f"Detection fired at t={u['detection_t']}s")
    if u["detection_reasons"]:
        for r in u["detection_reasons"]:
            print(f"  - {r}")
    print(f"First real trip at t={u['times']['trip_1_t']}s "
          f"(lead time: {u['lead_time_to_first_trip_s']}s)")
    print(f"Uncorrected collapse at t={u['collapse_t']}s "
          f"(lead time to collapse: {u['lead_time_to_collapse_s']}s)")
    if result["corrected"]:
        c = result["corrected"]
        print(f"Corrected branch collapse: {c['collapse_t']}")
        for a in c["actions_taken"]:
            print(f"  - {a}")
    print(f"Saved to {RUNS_DIR / 'latest.json'}")


if __name__ == "__main__":
    main()
