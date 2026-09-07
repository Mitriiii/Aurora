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

## Out of scope for this MVP

Live GPS tracking, in-app chat, payments/invoicing, a driver mobile app, customs services,
public carrier ratings, or carbon-credit trading — none of that is relevant here; this is a
single-purpose grid-stability demo. Closed-loop control of a real system is explicitly out of
scope: any real pilot would start with read-only access to a slice of real PMU data in
advisory-only mode.
