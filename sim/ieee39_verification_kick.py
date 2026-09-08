"""
IEEE 39-bus toolchain verification: NOT a scenario design choice.

The zero-disturbance baseline (ieee39_phase1_baseline.py) is flat by
construction -- it proves nothing about whether TDS actually produces
correct dynamic behavior on this new, larger network. This script applies
one arbitrary, generic, briefly-toggled line trip-and-reclose (Line_1,
picked only because it's first in the index -- no significance) purely to
confirm the solver responds sensibly: an oscillation appears and
propagates. This is the IEEE 39-bus equivalent of the Kundur Phase 0 plot,
which relied on that case's own stock disturbance -- there is no such
stock disturbance here, so a minimal generic one stands in for it.

This is explicitly NOT the fault mechanism. No calibrated fault magnitude,
tie-line choice, or generator selection here should be reused for that --
this kick is disposable, arbitrary, and exists only to prove the pipe
works end to end on the new network.

Also verifies the 60->50 Hz change (sim.ieee39_system.FN_HZ) actually
changes the dynamics, not just a config label: runs the identical kick at
fn=60 and fn=50, measures the dominant oscillation frequency of the
resulting swing (FFT of GENCLS_1's omega, the generator with the largest
response) and RoCoF immediately after the kick, and checks the observed
f_osc(50)/f_osc(60) ratio against the theoretical sqrt(50/60) = 0.9129
predicted by linearizing the swing equation (see sim/ieee39_system.py's
module docstring for the derivation).

Run: python -m sim.ieee39_verification_kick
"""
from __future__ import annotations

from pathlib import Path

import andes
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks

from sim.ieee39_system import load_case39_matpower, FN_HZ, CASE_PATH, GENERATOR_DYNAMICS_BY_BUS

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

KICK_LINE = "Line_1"
KICK_T = 2.0
KICK_DURATION = 0.06


def build_kicked_system(fn: float):
    ss = andes.load(str(CASE_PATH), setup=False, no_output=True)
    ss.config.freq = fn
    gens = list(zip(ss.PV.idx.v, ss.PV.bus.v)) + list(zip(ss.Slack.idx.v, ss.Slack.bus.v))
    for gi, (gen_idx, bus) in enumerate(gens, start=1):
        params = GENERATOR_DYNAMICS_BY_BUS[int(bus)]
        ss.add('GENCLS', dict(
            idx=f'GENCLS_{gi}', bus=bus, gen=gen_idx,
            Sn=params['Sn'], Vn=345.0, fn=fn,
            D=params['D'], M=2 * params['H'],
            ra=params['ra'], xd1=params['xd1'],
        ))
    ss.add('Toggle', dict(model='Line', dev=KICK_LINE, t=KICK_T))
    ss.add('Toggle', dict(model='Line', dev=KICK_LINE, t=KICK_T + KICK_DURATION))
    ss.setup()
    return ss


def run_kick(fn: float, tf: float = 30.0):
    ss = build_kicked_system(fn)
    ss.PFlow.run()
    assert ss.PFlow.converged
    ss.TDS.config.tf = tf
    ss.TDS.run()
    assert ss.TDS.converged, f"verification kick failed to converge at fn={fn} -- toolchain problem"
    t = ss.dae.ts.t
    x = ss.dae.ts.x
    omega_addr = ss.GENCLS.omega.a
    gen_names = list(ss.GENCLS.idx.v)
    return t, x, omega_addr, gen_names


def dominant_frequency_hz(t: np.ndarray, signal: np.ndarray, t_start: float) -> float:
    """FFT-based dominant oscillation frequency (Hz) of `signal` for t >= t_start."""
    mask = t >= t_start
    tt, ss_ = t[mask], signal[mask] - np.mean(signal[mask])
    dt = np.median(np.diff(tt))
    n = len(ss_)
    spec = np.abs(np.fft.rfft(ss_ * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=dt)
    spec[freqs < 0.02] = 0  # ignore DC / near-DC
    peak_i = np.argmax(spec)
    return float(freqs[peak_i])


def period_based_frequency_hz(t: np.ndarray, signal: np.ndarray, t_start: float) -> float | None:
    """Cross-check via peak-to-peak timing (independent of FFT windowing)."""
    mask = t >= t_start
    tt, ss_ = t[mask], signal[mask]
    peaks, _ = find_peaks(ss_)
    if len(peaks) < 2:
        return None
    periods = np.diff(tt[peaks])
    return float(1.0 / np.mean(periods))


def main():
    andes.config_logger(stream_level=30)

    results = {}
    for fn in (60.0, 50.0):
        t, x, omega_addr, gen_names = run_kick(fn)
        gi = gen_names.index('GENCLS_1')
        omega1 = x[:, omega_addr[gi]]
        freq_hz_series = omega1 * fn

        f_fft = dominant_frequency_hz(t, omega1, t_start=KICK_T)
        f_period = period_based_frequency_hz(t, omega1, t_start=KICK_T)

        # RoCoF: max |d(freq)/dt| in the first 2 seconds after the kick.
        window = (t >= KICK_T) & (t <= KICK_T + 2.0)
        rocof = float(np.max(np.abs(np.gradient(freq_hz_series[window], t[window]))))

        results[fn] = dict(t=t, x=x, omega_addr=omega_addr, gen_names=gen_names,
                            f_fft=f_fft, f_period=f_period, rocof=rocof)
        print(f"fn={fn:.0f} Hz: dominant oscillation freq (FFT) = {f_fft:.4f} Hz, "
              f"(peak-timing cross-check) = {f_period}, RoCoF (max, first 2s) = {rocof:.4f} Hz/s")

    f60, f50 = results[60.0]['f_fft'], results[50.0]['f_fft']
    ratio_observed = f50 / f60 if f60 > 0 else float('nan')
    ratio_theory = np.sqrt(50.0 / 60.0)
    print()
    print(f"Observed f_osc(50)/f_osc(60) = {f50:.4f}/{f60:.4f} = {ratio_observed:.4f}")
    print(f"Theoretical sqrt(50/60)      = {ratio_theory:.4f}")
    print(f"Difference: {abs(ratio_observed - ratio_theory):.4f} "
          f"({100*abs(ratio_observed-ratio_theory)/ratio_theory:.1f}% relative)")
    if abs(ratio_observed - ratio_theory) / ratio_theory < 0.15:
        print("CONSISTENT with 50 Hz swing-equation scaling (within 15%).")
    else:
        print("NOT CLEARLY CONSISTENT -- the arithmetic does not check out; do not report this as verified.")

    rocof60, rocof50 = results[60.0]['rocof'], results[50.0]['rocof']
    print(f"\nRoCoF ratio RoCoF(50)/RoCoF(60) = {rocof50/rocof60:.4f} "
          f"(expect roughly 50/60={50/60:.4f} if the post-kick power imbalance is fn-independent)")

    # Plot the fn=50 (production) run, since that's what the rest of the
    # project will use going forward.
    r = results[FN_HZ]
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, name in enumerate(r['gen_names']):
        ax.plot(r['t'], r['x'][:, r['omega_addr'][i]], label=f"GENCLS {name}", linewidth=1.2)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Rotor speed, omega (p.u.)")
    ax.set_title(f"IEEE 39-bus toolchain verification: generic brief trip-reclose on {KICK_LINE} at t={KICK_T}s, "
                 f"fn={FN_HZ:.0f} Hz\n(NOT a scenario design choice -- arbitrary line, exists only to prove TDS works here)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    out_path = REPORTS_DIR / "ieee39_verification_kick.png"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)

    omega_all = r['x'][:, r['omega_addr']]
    print()
    print(f"[fn={FN_HZ:.0f} Hz, saved plot] PFlow/TDS converged.")
    print(f"Max omega deviation from 1.0 p.u. after kick: {np.max(np.abs(omega_all - 1.0)):.6f}")
    print("Plot saved to:", out_path)


if __name__ == "__main__":
    main()
