# AURORA — Grid Stability Intelligence

**SIMULATION ONLY.** This is a proof-of-concept demo built entirely on open-source power
system simulators (ANDES) and public data. It is **not** connected to, and has never been
connected to, any real utility SCADA/EMS system, Iberdrola, Red Eléctrica, or any live control
system. Every simulated result is clearly labeled `SIMULATED`; anything pulled from ENTSO-E/ESIOS
is labeled `PUBLIC HISTORICAL/LIVE DATA`. See Section 8 of the original build brief.

It demonstrates how a detection-and-correction system could have caught the physical precursors
to the 28 April 2025 Iberian Peninsula blackout minutes before it happened — using ANDES's
built-in Kundur two-area, four-machine benchmark system (the textbook benchmark for exactly the
kind of lightly-damped, low-frequency inter-area oscillation the real event exhibited), a
rule-based early-warning detector, and a genuine counterfactual "corrected" branch.

## What's real vs. modeled

- **Real, cited numbers**: the ~0.6 Hz / ~0.2 Hz precursor oscillations, the ~2.3s system
  inertia, Spain's ±0.98 power-factor grid code, the three generation trips ~19s/21s apart, and
  the ~27-second first-trip-to-collapse window are all taken from the ENTSO-E Expert Panel
  investigation and are reproduced as scenario parameters (see `sim/kundur_system.py`).
- **Modeled, not real**: the network itself is the 4-machine Kundur benchmark, not a model of
  Spain's grid. Absolute MW/kV figures will not match the real event. What's preserved is the
  *mechanism*: voltage rising while frequency falls, an under-damped oscillation, a short cascade
  window, and a genuine counterfactual where early correction prevents collapse.
- **Detection**: rule-based/physics-threshold (Section 4.4), not machine learning — real UFLS
  schemes are rule-based too. `detect/gnn_detector.py`-style ML detection (referencing
  arXiv:2404.16134) is the documented v2 path, not built here.

## Setup

Requires Python 3.11 (ANDES does not yet support 3.13+). A conda env is the fastest path:

```bash
conda create -n aurora python=3.11 -c conda-forge
conda activate aurora
pip install andes pandapower fastapi "uvicorn[standard]" websockets numpy pandas
```

## Running it

```bash
conda activate aurora

# Phase 0 sanity check: unmodified Kundur case runs end to end
python -c "import andes; ss=andes.load(andes.get_case('kundur/kundur_full.xlsx')); ss.PFlow.run(); ss.TDS.config.tf=30; ss.TDS.run(); print(ss.TDS.converged)"

# Run the full scenario from the command line (writes data/runs/latest.json)
python -m sim.run_scenario

# Generate the forensic report from the latest run
python -m reports.report_generator

# Start the dashboard server
uvicorn server.main:app --reload --port 8000
# open http://localhost:8000, click "Run scenario", then "Play"
```

## Optional: real-data credibility ticker

Not required for the core demo (Phases 1-3 never depend on it). To enable the "real grid, right
now" ticker:

```bash
pip install entsoe-py pandas
export ENTSOE_API_KEY=...   # register at the ENTSO-E Transparency Platform,
                             # email transparency@entsoe.eu, subject "Restful API access"
```

ESIOS (`data/esios_client.py`) similarly needs `ESIOS_API_KEY` (email consultasios@ree.es) and is
not wired into the dashboard by default.

## Repository layout

```
sim/       ANDES scenario construction, PMU-style stream formatting, the run driver
detect/    Phase 3 rule-based early-warning detector
control/   Phase 4 corrective-action catalog (human-readable descriptions)
data/      Phase 7 ENTSO-E / ESIOS clients (credibility layer, optional)
server/    FastAPI + WebSocket backend
web/       Dashboard frontend (vanilla HTML/CSS/JS, no build step)
reports/   Phase 6 forensic report generator
```

## IEEE 39-bus network (Phase 7, in progress)

A second, larger network (`sim/ieee39_system.py`, `sim/ieee39_scenario.py`) is being brought up
in parallel, per the build brief's Section 4.1 "this scales" argument. `case39.m` is pulled from
MATPOWER's own GitHub repo and imported via ANDES's MATPOWER support; since raw MATPOWER format
carries no dynamics, minimal (Phase 0/1 toolchain check) or full (fault-mechanism work) generator
models are added on top, sourced from ANDES's bundled `ieee39_full.xlsx` and cited explicitly in
code, never invented.

Facts worth keeping visible, the same way Kundur's own caveats are documented above:

- **Bus 39 is not a real generator.** Per `case39.m`'s own header comment, it's a lumped
  equivalent for "the interconnection to rest of US/Canada" (added by the case's original
  authors). Excluded from all fault-target selection.
- **Generator model coverage: all 10 generators have a functioning exciter, not just the 3 used
  in the current fault.** `sim/ieee39_scenario.py`'s `_build_base39()` attaches GENROU + IEEEX1
  (exciter) + TGOV1N (governor) to every one of the 10 generators; `FAULT_GENS_39` (currently
  30/31/38) only controls which 3 get their VRMIN ramped as the fault. Confirmed live
  (`ss.IEEEX1.n == 10`, every one actively regulating). This means the calibration finding that a
  *single* one of these generators at 0.75×VRMAX could collapse the whole network by itself is a
  real statement about this network's electrical stiffness, not an artifact of missing AVR
  coverage elsewhere.
- **The fault mechanism (topology weakening + excitation ramp) went through two redesigns before
  being trusted**, following the same isolation-counterfactual discipline used on the Kundur
  mechanism: v1's islanding target and excitation target were the same generator (confounded,
  both "halves" collapsed alone); v2.0's excitation magnitude was independently sufficient to
  collapse the network from any one of its three target generators alone. v2.1 (current) has both
  halves confirmed marginal-but-insufficient alone (70.9% and 98.4% of the collapse threshold
  respectively) before any combined result is reported. See the module docstring in
  `sim/ieee39_scenario.py` for the full derivation and the isolation-counterfactual results.
- **Not yet wired into the dashboard.** The 39-bus work exists as standalone scripts
  (`python -m sim.run_ieee39_scenario`, `python -m sim.run_ieee39_isolation_checks`) producing
  static plots in `reports/`, not the interactive `server/main.py` + `web/` dashboard, which still
  runs the Kundur scenario only.
- **The Kundur-validated detector does not transfer to this network, and the honest lead time is
  short.** `detect/threshold_detector.ThresholdDetector` (a magnitude threshold on a P/Q-derived
  reactive-margin proxy) false-fires on both isolation counterfactuals here within 10-12 seconds --
  ordinary AVR transients on generators not even under fault exceed its Kundur-calibrated
  threshold. Diagnosis showed the underlying reason is structural, not a tuning miss: bus 30's
  voltage (the bus that actually crosses the collapse threshold) is **nearly identical** between
  the excitation-alone counterfactual and the combined fault for the first ~57 seconds -- no
  causal detector can tell these two futures apart before they actually diverge. A redesigned
  detector (`detect/sustained_growth_detector.SustainedGrowthDetector`) tracks bus voltage
  directly (not the margin proxy, which turned out not to discriminate at all on this network) and
  fires on a "plateaued, then broke past that plateau" pattern rather than a magnitude threshold.
  Validated against all three cases (silent on both non-collapsing counterfactuals over their full
  horizon, fires on the real fault) plus a causal check (confirmed the firing tick shows a real,
  ~3x-larger breakout than the same tick's noise level in the benign case, which does not continue
  to climb in the following 6s). Result: **detection at t=64.2s, collapse at t=66.5s -- a 2.3s
  lead time, shorter than the ~4s SCADA refresh cycle it's being compared against.** Reported as
  found, not adjusted to look better; see `sim/run_ieee39_detection_check.py`.

## Out of scope for this MVP

Live GPS tracking, in-app chat, payments/invoicing, a driver mobile app, customs services,
public carrier ratings, or carbon-credit trading — none of that is relevant here; this is a
single-purpose grid-stability demo. Closed-loop control of a real system is explicitly out of
scope: any real pilot would start with read-only access to a slice of real PMU data in
advisory-only mode.
