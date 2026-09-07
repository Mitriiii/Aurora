"""
Builds the AURORA fault scenario on top of ANDES's built-in Kundur two-area,
four-machine benchmark system.

The Kundur system is the textbook benchmark for lightly-damped, low-frequency
inter-area oscillations -- the same phenomenon (~0.6 Hz and ~0.2 Hz modes)
observed as precursors to the real 28 April 2025 Iberian blackout. We layer
three real-event mechanisms on top of the stock case:

  1. Reduced system inertia (generator M/2H scaled down toward the ~2.3s
     regulatory floor cited in the ENTSO-E investigation).
  2. A capacitive reactive-power surge injected near Area 2 (bus 8), standing
     in for the excess reactive power that lightly-loaded EHV/cable circuits
     produce at midday load, which the real generating fleet failed to
     absorb (the "under-excitation" failure mode). This is switched on by a
     Toggle event partway through the run, and is exactly what a corrective
     action can switch back off.
  3. Three scripted "distributed generation" trip events, modeled as negative
     PQ (i.e. generation) injections that disconnect via Toggle events. Their
     relative sizes and timing intervals mirror the real cascade: three trips
     at t0, t0+19s, t0+21s, closing out the real 27-second collapse window.

This module builds *both* branches (uncorrected and corrected) from the same
base case so the two runs are genuinely independent numerical integrations
sharing identical initial conditions -- not a scripted animation.

NOTE ON REALISM: this is a small, four-machine textbook benchmark, not a
real network model of Spain. Absolute MW/kV figures will not match the real
event. What is preserved faithfully is the *mechanism*: voltage rising while
frequency falls, an under-damped oscillation growing rather than damping,
and a short cascade window between the first trip and collapse. See
docs/scenario_notes.md for the exact scaling choices.
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
SURGE_BUS = 8                   # capacitive surge injected at the tie-line bus
BATTERY_BUS = 10                # modeled storage dispatch location

INERTIA_SCALE = 0.42            # scales GENROU M toward the ~2.3s floor
SURGE_B_PU = 14.0                # total capacitive susceptance (p.u. on Sn=100 MVA)
SURGE_STAGES = 3                # surge is split into equal banks so a correction can unwind it gradually
SURGE_UNWIND_STEP_S = 1.6       # spacing between staged bank de-energizations during correction
LINE_KICK_IDX = "Line_4"        # tie-line branch used to kick off oscillation
COLLAPSE_GENS = [2, 3, 4]       # generators shed in the final cascade/UFLS event

PF_LIMIT = 0.98                 # Spain's grid-code reactive power-factor band


@dataclass
class ScenarioTimes:
    """All times are simulation seconds from t=0."""
    line_kick_t: float = 2.0
    line_kick_duration: float = 0.06
    surge_on_t: float = 8.0
    trip_1_t: float = 22.0
    trip_2_t: float = 41.0      # trip_1_t + 19s, matching the real interval
    trip_3_t: float = 43.0      # trip_1_t + 21s, matching the real interval
    horizon_t: float = 60.0

    # Benign-scenario-only: the real event's SECOND precursor oscillation
    # (~0.2 Hz, 12:16-12:22 CEST) came roughly 13 minutes after the first
    # (~0.6 Hz, 12:03-12:07). Compressed here to a same-order-of-magnitude
    # gap so both precursors, and their self-damping, fit inside one run.
    benign_second_kick_t: float = 20.0

    @property
    def collapse_budget_t(self) -> float:
        """Real event: ~27s from first trip to total collapse."""
        return self.trip_1_t + 27.0


def _add_common_devices(ss, times: ScenarioTimes, include_first_kick: bool = True):
    """Add the surge shunt, the three trip-PQ devices, and (by default) the
    first oscillation kick -- present (but not yet toggled beyond this) in
    every branch. `include_first_kick=False` is used by the Phase 1
    zero-disturbance baseline, which must not perturb the system at all."""

    bank_b = SURGE_B_PU / SURGE_STAGES
    for s in range(1, SURGE_STAGES + 1):
        ss.add('Shunt', dict(idx=f'surge_bank_{s}', bus=SURGE_BUS,
                              Vn=230, g=0.0, b=bank_b, u=0))

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


def build_healthy(times: ScenarioTimes | None = None):
    """Phase 1 baseline: the wired pipeline (reduced inertia, governor fix,
    the same devices present in every other scenario) with ZERO disturbance
    -- no line kick, no surge, no trips. Must stay flat. This is the
    "everything normal" reference the fault scenarios deviate from."""
    times = times or ScenarioTimes()
    ss = _base_system(times)
    _add_common_devices(ss, times, include_first_kick=False)
    ss.setup()
    return ss, times


def build_benign(times: ScenarioTimes | None = None):
    """Non-cascading control scenario: the real event's own two precursor
    oscillations (~0.6 Hz at 12:03-12:07 and ~0.2 Hz at 12:16-12:22 CEST)
    that wobbled and self-damped WITHOUT any reactive surge, generation
    trip, or collapse -- operators handled both in real life. No surge bank
    and no trip is ever toggled here; only two brief tie-line perturbations
    (using two different lines, as the real precursors were distinct
    events) that the grid must damp out on its own.

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
    """The real, uncorrected timeline: surge switches on, all three
    generation trips fire on schedule, no intervention."""
    times = times or ScenarioTimes()
    ss = _base_system(times)

    _add_common_devices(ss, times)

    for s in range(1, SURGE_STAGES + 1):
        ss.add('Toggle', dict(model='Shunt', dev=f'surge_bank_{s}', t=times.surge_on_t))
    ss.add('Toggle', dict(model='PQ', dev='trip_gen_1', t=times.trip_1_t))
    ss.add('Toggle', dict(model='PQ', dev='trip_gen_2', t=times.trip_2_t))
    ss.add('Toggle', dict(model='PQ', dev='trip_gen_3', t=times.trip_3_t))

    # Final cascading collapse: protection relays + UFLS finish the job,
    # matching the real event's ~27s first-trip-to-collapse window. This
    # never fires in the corrected branch because AURORA's intervention
    # happens well before it would be scheduled.
    for g in COLLAPSE_GENS:
        ss.add('Toggle', dict(model='GENROU', dev=g, t=times.collapse_budget_t))
    ss.add('Toggle', dict(model='Line', dev='Line_4', t=times.collapse_budget_t))
    ss.add('Toggle', dict(model='Line', dev='Line_5', t=times.collapse_budget_t))
    ss.add('Toggle', dict(model='Line', dev='Line_6', t=times.collapse_budget_t))

    ss.setup()
    return ss, times


def build_corrected(times: ScenarioTimes, detection_t: float):
    """The AURORA-corrected branch: identical initial conditions and the
    same surge onset, but AURORA intervenes at `detection_t` -- switching
    off the reactive surge, cancelling any trip event still in the future,
    and dispatching modeled storage. Any trip scheduled *before*
    detection_t already happened in reality and is kept, matching the
    honest framing that correction only affects what hasn't happened yet.
    """
    ss = _base_system(times)

    _add_common_devices(ss, times)

    for s in range(1, SURGE_STAGES + 1):
        ss.add('Toggle', dict(model='Shunt', dev=f'surge_bank_{s}', t=times.surge_on_t))

    trip_times = {'trip_gen_1': times.trip_1_t, 'trip_gen_2': times.trip_2_t, 'trip_gen_3': times.trip_3_t}
    actions = []
    for dev, t in trip_times.items():
        if t < detection_t:
            ss.add('Toggle', dict(model='PQ', dev=dev, t=t))
            actions.append(f"{dev} trip already in progress at detection (t={t:.1f}s) -- not preventable")
        else:
            actions.append(f"{dev} trip scheduled for t={t:.1f}s -- CANCELLED by protection re-tuning")

    # Corrective action 1: reactive power redispatch -- unwind the surge banks
    # one at a time rather than all at once, so the correction itself doesn't
    # inject a second large transient.
    for s in range(1, SURGE_STAGES + 1):
        t_unwind = detection_t + (s - 1) * SURGE_UNWIND_STEP_S
        ss.add('Toggle', dict(model='Shunt', dev=f'surge_bank_{s}', t=t_unwind))
    actions.append(f"reactive-power redispatch: surge banks de-energized in {SURGE_STAGES} stages starting t={detection_t:.1f}s")

    # Corrective action 2: dispatch modeled storage to backstop the disturbance.
    ss.PQ.p0.v[ss.PQ.idx.v.index('battery')] = -1.2
    ss.add('Toggle', dict(model='PQ', dev='battery', t=detection_t))
    actions.append(f"modeled battery storage dispatched (1.2 p.u.) at t={detection_t:.1f}s")

    ss.setup()
    return ss, actions
