"""
Builds the AURORA fault scenario on top of ANDES's built-in Kundur two-area,
four-machine benchmark system.

The Kundur system is the textbook benchmark for lightly-damped, low-frequency
inter-area oscillations -- the same phenomenon (~0.6 Hz and ~0.2 Hz modes)
observed as precursors to the real 28 April 2025 Iberian blackout. We layer
three real-event mechanisms on top of the stock case:

  1. Reduced system inertia (generator M/2H scaled down toward the ~2.3s
     regulatory floor cited in the ENTSO-E investigation).
  2. Generator under-excitation, modeled as a GRADUAL RAMP on the exciter's
     minimum field-voltage limit (EXDC2.VRMIN) for the Area-2 machines,
     starting from a sustained single tie-line loss. This is BUILD_PROMPT.md
     Section 6 Phase 2's actual specified mechanism -- a real AVR/exciter
     capability degrading over time -- not an external shunt admittance
     injected onto a bus (an earlier version of this file did that; it was
     removed because a 14 p.u. shunt has no real-device analogue and made
     the local admittance numerically near-singular; see git history and
     the audit that flagged it).
  3. Three scripted "distributed generation" trip events, modeled as negative
     PQ (i.e. generation) injections that disconnect via Toggle events. Their
     relative sizes and timing intervals mirror the real cascade: three trips
     19s and 21s apart, matching the real event's spacing.

This module builds *both* branches (uncorrected and corrected) from the same
base case so the two runs are genuinely independent numerical integrations
sharing identical initial conditions -- not a scripted animation.

THE EXCITATION RAMP IS CONTINUOUS, NOT A DISCRETE EVENT: ANDES model
parameters are static within a single TDS.run() call, so this module cannot
express a ramp by itself. `apply_excitation_ramp()` below must be called by
the run loop (sim/run_scenario.py) at every tick, mutating EXDC2.VRMIN
directly between chunked TDS.run() calls -- confirmed to take effect
immediately (see the diagnostic session that designed this mechanism).

NOTE ON REALISM: this is a small, four-machine textbook benchmark, not a
real network model of Spain. Absolute MW/kV figures will not match the real
event. What is preserved faithfully is the *mechanism*: a real exciter
capability (the field-voltage floor) degrading gradually, causing voltage to
climb once the generators can no longer reduce excitation enough to absorb
what the grid needs absorbed, and a short cascade window between the first
trip and whatever the physics actually produces.
"""
from __future__ import annotations

import andes
from dataclasses import dataclass, field

SBASE_MVA = 100.0

# Real-event proportions preserved: 317 : 730 : 550 MW, scaled to this
# benchmark's much smaller (~2800 MW) generating capacity.
TRIP_1_PU = 0.70   # ~ "317 MW"-equivalent share of this benchmark's capacity
TRIP_2_PU = 1.61   # ~ "730 MW"-equivalent
TRIP_3_PU = 1.22   # ~ "550 MW"-equivalent

TRIP_BUSES = [9, 8, 9]          # Area-2 buses, near the Area1/Area2 tie
BATTERY_BUS = 10                # modeled storage dispatch location

INERTIA_SCALE = 0.42            # scales GENROU M toward the ~2.3s floor
LINE_KICK_IDX = "Line_4"        # tie-line branch used to kick off the first precursor oscillation
TIE_TRIP_LINE = "Line_5"        # sustained (not reclosed) single tie-line loss -- a real device event,
                                 # not an external admittance -- that triggers the excitation stress

# Under-excitation fault: which generators lose reactive-absorption headroom,
# and how far. EXDC2.VRMIN defaults to -4.16 p.u. in this case file (read
# and cached at build time, not hardcoded, in case the case file changes).
EXCITATION_FAULT_GENS = [3, 4]      # Area-2 machines, nearest the tie/trip region
VRMIN_FAULT_TARGET = 3.5            # p.u. -- raised well above the generators' natural
                                     # operating field voltage (~1.8-2.2 p.u. steady state),
                                     # so once the ramp catches up, they can no longer
                                     # reduce excitation enough to absorb reactive power.
EXCITATION_RAMP_DURATION_S = 14.0   # gradual, not a step: ramps over ~14s once triggered

PF_LIMIT = 0.98                 # Spain's grid-code reactive power-factor band


@dataclass
class ScenarioTimes:
    """All times are simulation seconds from t=0."""
    line_kick_t: float = 2.0
    line_kick_duration: float = 0.06

    # Sustained single tie-line loss AND the start of the excitation-limit
    # ramp -- the initiating event and the onset of the degrading exciter
    # capability happen together.
    excitation_fault_start_t: float = 4.0

    trip_1_t: float = 22.0
    trip_2_t: float = 41.0      # trip_1_t + 19s, matching the real interval
    trip_3_t: float = 43.0      # trip_1_t + 21s, matching the real interval
    horizon_t: float = 60.0

    # Benign-scenario-only: the real event's SECOND precursor oscillation
    # (~0.2 Hz, 12:16-12:22 CEST) came roughly 13 minutes after the first
    # (~0.6 Hz, 12:03-12:07). Compressed here to a same-order-of-magnitude
    # gap so both precursors, and their self-damping, fit inside one run.
    benign_second_kick_t: float = 20.0


def _add_common_devices(ss, times: ScenarioTimes, include_first_kick: bool = True):
    """Add the three trip-PQ devices, the (inert) battery, and (by default)
    the first oscillation kick -- present in every branch.
    `include_first_kick=False` is used by the Phase 1 zero-disturbance
    baseline, which must not perturb the system at all."""

    for i, (bus, mw) in enumerate(zip(TRIP_BUSES, [TRIP_1_PU, TRIP_2_PU, TRIP_3_PU]), start=1):
        ss.add('PQ', dict(idx=f'trip_gen_{i}', bus=bus, Vn=230,
                           p0=-mw, q0=0.0, u=1))

    ss.add('PQ', dict(idx='battery', bus=BATTERY_BUS, Vn=230,
                       p0=0.0, q0=0.0, u=0))

    if include_first_kick:
        ss.add('Toggle', dict(model='Line', dev=LINE_KICK_IDX, t=times.line_kick_t))
        ss.add('Toggle', dict(model='Line', dev=LINE_KICK_IDX, t=times.line_kick_t + times.line_kick_duration))


def _base_system(times: ScenarioTimes):
    """Shared setup: load the stock case, apply the reduced-inertia
    background condition and the governor-limit fix. Every scenario
    (healthy, benign, uncorrected, corrected) starts from this.

    IMPORTANT: the stock kundur_full.xlsx case ships with its OWN built-in
    disturbance -- a Toggle that trips Line_8 at t=2.0s (confirmed via
    `ss.Toggle.as_df()` on the unmodified case). Phase 0 intentionally uses
    that stock event to prove the toolchain works. Every scenario we script
    ourselves must NOT inherit it silently, or "zero disturbance" and
    "exactly the two real precursor kicks" both become false claims. It is
    disabled here, once, for every AURORA-authored scenario.
    """
    ss = andes.load(andes.get_case('kundur/kundur_full.xlsx'), setup=False, no_output=True)
    ss.Toggle.u.v = [0]  # disable the stock case's built-in Line_8 @ t=2s event
    ss.GENROU.M.v = [v * INERTIA_SCALE for v in ss.GENROU.M.v]
    ss.TGOV1.VMIN.v = [v * 0.5 for v in ss.TGOV1.VMIN.v]
    return ss


def _cache_vrmin_healthy(ss):
    """Reads and stashes each excitation-faulted generator's stock VRMIN
    value on the system object itself, before any mutation, so the ramp has
    a real reference point instead of a hardcoded number."""
    idxs = [ss.EXDC2.idx.v.index(g) for g in EXCITATION_FAULT_GENS]
    ss._excitation_fault_idx = idxs
    ss._vrmin_healthy = ss.EXDC2.VRMIN.v[idxs[0]]
    return ss


def excitation_ramp_value(t: float, times: ScenarioTimes, vrmin_healthy: float,
                           detection_t: float | None = None) -> float:
    """Computes the current VRMIN value for the excitation-faulted
    generators at time t. If `detection_t` is given and t has reached it,
    the ramp reverses back toward the healthy value over the same duration
    -- modeling AURORA restoring the exciters' reactive-absorption
    capability (the corrected branch)."""
    start = times.excitation_fault_start_t
    dur = EXCITATION_RAMP_DURATION_S

    if detection_t is not None and t >= detection_t:
        fault_frac_at_detection = min(1.0, max(0.0, (detection_t - start) / dur))
        recovery_frac = min(1.0, (t - detection_t) / dur)
        frac = fault_frac_at_detection * (1.0 - recovery_frac)
    else:
        frac = min(1.0, max(0.0, (t - start) / dur))

    return vrmin_healthy + frac * (VRMIN_FAULT_TARGET - vrmin_healthy)


def apply_excitation_ramp(ss, t: float, times: ScenarioTimes, detection_t: float | None = None) -> float:
    """Mutates EXDC2.VRMIN on the faulted generators in place for the
    current tick. Must be called every tick from the run loop, between
    chunked TDS.run() calls -- ANDES parameters are static within a single
    run() call. Returns the VRMIN value just applied (for logging)."""
    value = excitation_ramp_value(t, times, ss._vrmin_healthy, detection_t)
    for i in ss._excitation_fault_idx:
        ss.EXDC2.VRMIN.v[i] = value
    return value


def build_healthy(times: ScenarioTimes | None = None):
    """Phase 1 baseline: the wired pipeline (reduced inertia, governor fix,
    the same devices present in every other scenario) with ZERO disturbance
    -- no line kick, no tie-line loss, no excitation ramp, no trips. Must
    stay flat. This is the "everything normal" reference the fault
    scenarios deviate from."""
    times = times or ScenarioTimes()
    ss = _base_system(times)
    _add_common_devices(ss, times, include_first_kick=False)
    ss.setup()
    return ss, times


def build_benign(times: ScenarioTimes | None = None):
    """Non-cascading control scenario: the real event's own two precursor
    oscillations (~0.6 Hz at 12:03-12:07 and ~0.2 Hz at 12:16-12:22 CEST)
    that wobbled and self-damped WITHOUT any excitation fault, generation
    trip, or collapse -- operators handled both in real life. No sustained
    tie-line loss and no excitation ramp is ever applied here; only two
    brief tie-line perturbations (using two different lines, as the real
    precursors were distinct events) that the grid must damp out on its own.

    This exists to test the detector for false alarms: a detector that
    fires on ordinary, self-recovering transient oscillation is not an
    early-warning system, it's a nuisance alarm generator."""
    times = times or ScenarioTimes()
    ss = _base_system(times)
    _add_common_devices(ss, times, include_first_kick=True)

    # Second precursor: a brief perturbation on a different tie-line branch,
    # well after the first has damped out, mirroring the real ~13-minute
    # gap between the two recorded precursor oscillations.
    ss.add('Toggle', dict(model='Line', dev='Line_5', t=times.benign_second_kick_t))
    ss.add('Toggle', dict(model='Line', dev='Line_5',
                          t=times.benign_second_kick_t + times.line_kick_duration))

    ss.setup()
    return ss, times


def build_uncorrected(times: ScenarioTimes | None = None):
    """The real, uncorrected timeline: a sustained single tie-line loss
    triggers a gradual excitation-limit ramp (applied tick-by-tick by the
    run loop via apply_excitation_ramp), all three generation trips fire on
    schedule, no intervention."""
    times = times or ScenarioTimes()
    ss = _base_system(times)

    _add_common_devices(ss, times)

    # Sustained tie-line loss -- a real device event, never reclosed.
    ss.add('Toggle', dict(model='Line', dev=TIE_TRIP_LINE, t=times.excitation_fault_start_t))

    ss.add('Toggle', dict(model='PQ', dev='trip_gen_1', t=times.trip_1_t))
    ss.add('Toggle', dict(model='PQ', dev='trip_gen_2', t=times.trip_2_t))
    ss.add('Toggle', dict(model='PQ', dev='trip_gen_3', t=times.trip_3_t))

    # No hardcoded final-collapse event. Whether and when this branch
    # collapses is entirely a product of the physics above plus whatever
    # the three trips do to it -- decided at run time by
    # detect.collapse_monitor.CollapseMonitor against real protective
    # thresholds, not asserted here.

    ss.setup()
    _cache_vrmin_healthy(ss)
    return ss, times


def build_corrected(times: ScenarioTimes, detection_t: float):
    """The AURORA-corrected branch: identical initial conditions and the
    same tie-line loss, but AURORA intervenes at `detection_t` -- the
    excitation ramp reverses back toward the healthy VRMIN (applied by the
    run loop via apply_excitation_ramp(..., detection_t=...)), any trip
    event still in the future is cancelled, and modeled storage is
    dispatched. Any trip scheduled *before* detection_t already happened in
    reality and is kept, matching the honest framing that correction only
    affects what hasn't happened yet.

    NOT YET RE-VALIDATED against the new excitation-ramp fault mechanism --
    kept mechanically consistent (no dangling references to the removed
    shunt code) but its behavior has not been run or reported.
    """
    ss = _base_system(times)

    _add_common_devices(ss, times)
    ss.add('Toggle', dict(model='Line', dev=TIE_TRIP_LINE, t=times.excitation_fault_start_t))

    trip_times = {'trip_gen_1': times.trip_1_t, 'trip_gen_2': times.trip_2_t, 'trip_gen_3': times.trip_3_t}
    actions = []
    for dev, t in trip_times.items():
        if t < detection_t:
            ss.add('Toggle', dict(model='PQ', dev=dev, t=t))
            actions.append(f"{dev} trip already in progress at detection (t={t:.1f}s) -- not preventable")
        else:
            actions.append(f"{dev} trip scheduled for t={t:.1f}s -- CANCELLED by protection re-tuning")

    actions.append(
        f"reactive-power redispatch: excitation limit (VRMIN) on generators "
        f"{EXCITATION_FAULT_GENS} ramped back toward its healthy value starting t={detection_t:.1f}s"
    )

    # Corrective action: dispatch modeled storage to backstop the disturbance.
    ss.PQ.p0.v[ss.PQ.idx.v.index('battery')] = -1.2
    ss.add('Toggle', dict(model='PQ', dev='battery', t=detection_t))
    actions.append(f"modeled battery storage dispatched (1.2 p.u.) at t={detection_t:.1f}s")

    ss.setup()
    _cache_vrmin_healthy(ss)
    return ss, actions
