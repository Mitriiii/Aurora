"""
Fault mechanism, ported to the IEEE 39-bus New England system. One step:
get the network into a fault-capable state and run it. Detection and the
benign scenario are NOT touched here.

WHY THIS NEEDS MORE THAN GENCLS: the Phase 0/1 toolchain check
(sim/ieee39_system.py) used the classical generator model (GENCLS) --
correct for "does TDS work at all," but GENCLS has no exciter, so there is
no VRMIN to ramp. The under-excitation mechanism requires a real AVR. This
module upgrades all 10 generators to GENROU + IEEEX1 (exciter) + TGOV1N
(governor), with every parameter read from ANDES's own bundled
ieee39_full.xlsx via direct model introspection (ss.GENROU.params, etc.),
not hand-transcribed -- avoiding the transcription-rounding bug that
briefly broke the Phase-1 recheck last round. IEEEX1 is "derived from
EXDC2 by varying the limiter bounds" per its own ANDES docstring, so it
carries the same VRMAX/VRMIN fields the Kundur mechanism used.

BUS 39 CONFIRMED NOT A REAL GENERATOR: per case39.m's own header comment
(the file's generator-type list, "10  39  interconnection to rest of
US/Canada") and its notes ("Bus 39, its generator and 2 connecting lines
were added [...] to represent the interconnection with the rest of the
eastern interconnect") -- not inferred from H=599.5s/xd1=0.005 alone,
though those values are consistent with a lumped equivalent. Excluded from
generator selection.

=== REDESIGN (v2): the two halves must be genuinely independent ===

v1 of this mechanism (islanding bus 25/generator 37 + VRMIN ramp
including generator 37) failed its own isolation counterfactuals: BOTH
halves collapsed the system alone, because generator 37 was simultaneously
the excitation-fault target AND the specific generator the topology event
isolated. The "combined" result was really the excitation fault doing all
the work. This version separates the two concerns by construction and
re-verifies independence before any combined claim (see
sim/run_ieee39_isolation_checks.py).

TOPOLOGY WEAKENING -- A THINNED CORRIDOR, NOT AN ISLAND, VERIFIED BY
EXHAUSTIVE BFS: removing Line_9 (bus4-14) and Line_26 (bus16-17) together.
Checked, not assumed: BFS from EVERY one of the 39 buses over the
remaining 44-line topology reaches all 39 buses every time -- confirmed
via networkx, not a single reference-bus check. This pair was selected
from all 562 non-bridge-edge pairs whose joint removal keeps the network
connected (of 46 lines, 11 are bridges -- single points of failure, all
9 real-generator ties among them plus one internal mesh bridge at
bus16-19 -- excluded outright since removing any bridge trivially
islands something regardless of pairing). Among the 562 safe pairs, this
one produces the largest increase in average shortest-path length
(+46.5%, vs the next-best +44.6%), with 490 MW combined pre-fault loading
-- a real, heavily-used corridor, not a token pick. The naively
highest-betweenness corridor (the serial chain Line_24/25/26, bus
14-15-16-17) was checked and REJECTED: bus 15 is degree-2 (isolated alone
by any two of its links), and removing Line_25+Line_26 disconnects an
11-bus cluster including three real generators (34, 35, 36) -- betweenness
rank alone was not sufcient without the explicit connectivity check.

GENERATOR SELECTION -- BY CONCRETE CONNECTIVITY MEASURE, NOT NARRATIVE:
candidates are the 9 real generators' own attachment buses, scored on two
measures computed directly from the graph:
  (a) shortest-path-length change (hops) to a fixed reference bus (bus 1)
      after the Line_9+Line_26 weakening, i.e. how exposed that generator
      is to the specific corridor being thinned;
  (b) edge-connectivity (Menger min-cut size) from the attachment bus to
      three distant reference buses (1, 16, 27), i.e. how many
      edge-disjoint paths exist in the UNMODIFIED topology -- a direct,
      reproducible "how thin is this bus, structurally" measure.
Results (attachment bus, degree, path-length change, min edge-connectivity):
    bus 30 (attach bus 2,  degree 4): path 2->2 (+0),  edge-conn 2
    bus 31 (attach bus 6,  degree 4): path 6->6 (+0),  edge-conn 2
    bus 32 (attach bus 10, degree 3): path 7->8 (+1),  edge-conn 2
    bus 33 (attach bus 19, degree 3): path 7->13 (+6), edge-conn 1  EXCLUDED (b)
    bus 34 (attach bus 20, degree 2): path 8->14 (+6), edge-conn 1  EXCLUDED (a)+(b)
    bus 35 (attach bus 22, degree 3): path 8->14 (+6), edge-conn 2  EXCLUDED (a)
    bus 36 (attach bus 23, degree 3): path 8->14 (+6), edge-conn 2  EXCLUDED (a)
    bus 37 (attach bus 25, degree 3): path 3->3 (+0),  edge-conn 2
    bus 38 (attach bus 29, degree 3): path 5->5 (+0),  edge-conn 2
Generators 33 and 34 are structurally thin regardless of this fault
(edge-connectivity 1 -- a single 2-edge cut, bus16-19 combined with any
one other edge, already suffices to isolate them; this is the same class
of fragility v1's bus 25 turned out to have). Generators 34/35/36 are all
directly adjacent to the new weakened corridor (+6 hops) and excluded on
that basis regardless of their connectivity score.

That leaves 30, 31, 37, 38 tied at the best available connectivity score
(2) with zero path-length exposure to the new corridor. Generator 37 is
deliberately NOT reused here even though it passes both measures on this
specific corridor -- it was v1's islanded target via a DIFFERENT 2-line
cut (Line_4+Line_40, still present and inert in this version), and
reusing it risks confounding this test with that prior, already-known
fragility. Selected: GENERATORS 30, 31, 38 -- a clean, independent set by
construction.

FAULT MAGNITUDES -- DERIVED FRESH FOR THESE THREE GENERATORS:
  - VRMIN ramp target = 0.75 * that generator's own VRMAX (same documented
    rule as v1, re-applied to the new generators, not the same numbers):
    bus30 -> 6.00, bus31 -> 3.90, bus38 -> 7.425.
  - Ramp duration = 3 * mean(Td10) of generators 30, 31, 38:
    mean(10.2, 6.56, 4.79) = 7.183s -> 3x = 21.55s.

A known governor-initialization clamp (TGOV1N's VMIN, on a couple of
units, worst on bus 39) produces the same benign "Initialization FAILED"
residual-mismatch warning seen on Kundur's TGOV1; fixed the same way
(VMIN halved for all 10 units) -- confirmed non-fatal, TDS reaches the
full requested horizon regardless.
"""
from __future__ import annotations

from dataclasses import dataclass

import andes

CASE_PATH_STR = str(__import__('pathlib').Path(__file__).resolve().parent.parent / "data" / "cases" / "case39.m")
FN_HZ = 50.0

# Full parameter sets, read via ANDES model introspection from
# andes.get_case('ieee39/ieee39_full.xlsx') (ss.GENROU.params / ss.IEEEX1.params
# / ss.TGOV1N.params), keyed by bus number -- not row order, not hand-typed.
GENROU_BY_BUS = {
    30: {'Sn': 1040.0, 'Vn': 34.5, 'D': 0.0, 'M': 87.36000000000001, 'ra': 0.0001346153846153846, 'xl': 0.01201923076923077, 'xd1': 0.02980769230769231, 'xd': 0.09615384615384616, 'xq': 0.06634615384615385, 'xd2': 0.0007615384615384616, 'xq1': 0.02980769230769231, 'xq2': 0.0007615384615384616, 'Td10': 10.2, 'Td20': 0.03, 'Tq10': 1.5, 'Tq20': 0.04},
    31: {'Sn': 836.0, 'Vn': 34.5, 'D': 0.0, 'M': 50.66159999999999, 'ra': 0.003229665071770335, 'xl': 0.04186602870813397, 'xd1': 0.0833732057416268, 'xd': 0.3528708133971292, 'xq': 0.3373205741626794, 'xd2': 0.035620813397129185, 'xq1': 0.0833732057416268, 'xq2': 0.035620813397129185, 'Td10': 6.56, 'Td20': 0.03, 'Tq10': 1.5, 'Tq20': 0.04},
    32: {'Sn': 843.7, 'Vn': 21.0, 'D': 0.0, 'M': 60.40892000000001, 'ra': 0.00045750859310181346, 'xl': 0.036031764845324166, 'xd1': 0.06293706293706294, 'xd': 0.29572122792461775, 'xq': 0.2809055351428233, 'xd2': 0.00304136541424677, 'xq1': 0.06293706293706294, 'xq2': 0.00304136541424677, 'Td10': 5.7, 'Td20': 0.03, 'Tq10': 1.5, 'Tq20': 0.04},
    33: {'Sn': 1174.8, 'Vn': 21.0, 'D': 0.0, 'M': 67.19855999999999, 'ra': 0.00018896833503575077, 'xl': 0.02511065713312904, 'xd1': 0.037112700034048346, 'xd': 0.223016683690841, 'xq': 0.21961184882533197, 'xd2': 0.0006835205992509364, 'xq1': 0.037112700034048346, 'xq2': 0.0006835205992509364, 'Td10': 5.69, 'Td20': 0.03, 'Tq10': 1.5, 'Tq20': 0.04},
    34: {'Sn': 1080.2, 'Vn': 15.5, 'D': 0.0, 'M': 56.1704, 'ra': 0.00012960562858729864, 'xl': 0.04999074245510091, 'xd1': 0.12219959266802445, 'xd': 0.620255508239215, 'xq': 0.5739677837437512, 'xd2': 0.0005286058137381966, 'xq1': 0.12219959266802445, 'xq2': 0.0005286058137381966, 'Td10': 5.4, 'Td20': 0.03, 'Tq10': 0.44, 'Tq20': 0.04},
    35: {'Sn': 1085.7, 'Vn': 15.5, 'D': 0.0, 'M': 75.56472000000001, 'ra': 0.0056645482177397075, 'xl': 0.020631850419084462, 'xd1': 0.04605323754259925, 'xd': 0.2339504467164042, 'xq': 0.2219766049553284, 'xd2': 0.042864511375149676, 'xq1': 0.04605323754259925, 'xq2': 0.042864511375149676, 'Td10': 7.3, 'Td20': 0.03, 'Tq10': 0.4, 'Tq20': 0.04},
    36: {'Sn': 1025.2, 'Vn': 12.5, 'D': 0.0, 'M': 54.13056, 'ra': 0.00026141240733515414, 'xl': 0.031408505657432695, 'xd1': 0.04779555208739758, 'xd': 0.28774873195474054, 'xq': 0.2848224736636754, 'xd2': 0.0020883730003901676, 'xq1': 0.04779555208739758, 'xq2': 0.0020883730003901676, 'Td10': 5.66, 'Td20': 0.03, 'Tq10': 1.5, 'Tq20': 0.04},
    37: {'Sn': 970.2, 'Vn': 12.5, 'D': 0.0, 'M': 47.151720000000005, 'ra': 0.0007070707070707071, 'xl': 0.028860028860028863, 'xd1': 0.05875077303648732, 'xd': 0.2989074417645846, 'xq': 0.2886002886002886, 'xd2': 0.006262626262626263, 'xq1': 0.05875077303648732, 'xq2': 0.006262626262626263, 'Td10': 6.7, 'Td20': 0.03, 'Tq10': 0.41, 'Tq20': 0.04},
    38: {'Sn': 1684.1, 'Vn': 34.5, 'D': 0.0, 'M': 116.20289999999999, 'ra': 0.00017813669022029573, 'xl': 0.017694911228549375, 'xd1': 0.03384597114185618, 'xd': 0.1250519565346476, 'xq': 0.12172673831720207, 'xd2': 0.0006971082477287573, 'xq1': 0.03384597114185618, 'xq2': 0.0006971082477287573, 'Td10': 4.79, 'Td20': 0.03, 'Tq10': 1.96, 'Tq20': 0.04},
    39: {'Sn': 1199.0, 'Vn': 345.0, 'D': 0.0, 'M': 1199.0, 'ra': 8.340283569641367e-05, 'xl': 0.0025020850708924102, 'xd1': 0.0050041701417848205, 'xd': 0.016680567139282735, 'xq': 0.0158465387823186, 'xd2': 0.00021684737281067553, 'xq1': 0.0050041701417848205, 'xq2': 0.00021684737281067553, 'Td10': 7.0, 'Td20': 0.03, 'Tq10': 0.7, 'Tq20': 0.04},
}

IEEEX1_BY_BUS = {
    30: {'TR': 0.0, 'TA': 0.06, 'TC': 0.0, 'TB': 0.0, 'TE': 0.25, 'TF1': 1.3, 'KF1': 0.23, 'KA': 10.1, 'KE': -0.05, 'VRMAX': 8.0, 'VRMIN': -8.0, 'E1': 1.7, 'SE1': 0.5, 'E2': 3.0, 'SE2': 2.0},
    31: {'TR': 0.0, 'TA': 0.05, 'TC': 0.0, 'TB': 0.0, 'TE': 0.41, 'TF1': 1.3, 'KF1': 0.23, 'KA': 10.1, 'KE': -0.05, 'VRMAX': 5.2, 'VRMIN': -5.0, 'E1': 3.0, 'SE1': 0.66, 'E2': 4.0, 'SE2': 0.88},
    32: {'TR': 0.0, 'TA': 0.06, 'TC': 0.0, 'TB': 0.0, 'TE': 0.5, 'TF1': 1.3, 'KF1': 0.23, 'KA': 10.1, 'KE': -0.02, 'VRMAX': 5.0, 'VRMIN': -5.0, 'E1': 3.0, 'SE1': 0.13, 'E2': 4.0, 'SE2': 0.34},
    33: {'TR': 0.0, 'TA': 0.06, 'TC': 0.0, 'TB': 0.0, 'TE': 0.5, 'TF1': 1.3, 'KF1': 0.23, 'KA': 10.1, 'KE': -0.05, 'VRMAX': 5.0, 'VRMIN': -5.0, 'E1': 3.0, 'SE1': 0.08, 'E2': 4.0, 'SE2': 0.31},
    34: {'TR': 0.0, 'TA': 0.02, 'TC': 0.0, 'TB': 0.0, 'TE': 0.785, 'TF1': 1.3, 'KF1': 0.23, 'KA': 40.0, 'KE': -0.04, 'VRMAX': 9.9, 'VRMIN': -9.9, 'E1': 3.0, 'SE1': 0.03, 'E2': 4.0, 'SE2': 0.91},
    35: {'TR': 0.0, 'TA': 0.02, 'TC': 0.0, 'TB': 0.0, 'TE': 0.471, 'TF1': 1.3, 'KF1': 0.23, 'KA': 10.1, 'KE': 1.0, 'VRMAX': 5.0, 'VRMIN': -5.0, 'E1': 3.0, 'SE1': 0.08, 'E2': 4.0, 'SE2': 0.25},
    36: {'TR': 0.0, 'TA': 0.02, 'TC': 0.0, 'TB': 0.0, 'TE': 0.73, 'TF1': 1.3, 'KF1': 0.23, 'KA': 40.0, 'KE': 1.0, 'VRMAX': 6.5, 'VRMIN': -6.5, 'E1': 3.0, 'SE1': 0.03, 'E2': 4.0, 'SE2': 0.74},
    37: {'TR': 0.0, 'TA': 0.02, 'TC': 0.0, 'TB': 0.0, 'TE': 0.528, 'TF1': 1.3, 'KF1': 0.23, 'KA': 10.1, 'KE': -0.05, 'VRMAX': 5.0, 'VRMIN': -5.0, 'E1': 3.0, 'SE1': 0.09, 'E2': 4.0, 'SE2': 0.28},
    38: {'TR': 0.0, 'TA': 0.02, 'TC': 0.0, 'TB': 0.0, 'TE': 0.95, 'TF1': 1.3, 'KF1': 0.23, 'KA': 40.0, 'KE': 1.0, 'VRMAX': 9.9, 'VRMIN': -9.9, 'E1': 3.0, 'SE1': 0.03, 'E2': 4.0, 'SE2': 0.85},
    39: {'TR': 0.0, 'TA': 0.02, 'TC': 0.0, 'TB': 0.0, 'TE': 0.95, 'TF1': 1.3, 'KF1': 0.23, 'KA': 10.1, 'KE': 1.0, 'VRMAX': 9.9, 'VRMIN': -9.9, 'E1': 3.0, 'SE1': 0.03, 'E2': 4.0, 'SE2': 0.85},
}

TGOV1N_BY_BUS = {
    30: {'R': 0.004807692307692308, 'VMAX': 10.504000000000001, 'VMIN': 1.04, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    31: {'R': 0.005980861244019139, 'VMAX': 8.778, 'VMIN': 0.836, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    32: {'R': 0.005926277112717791, 'VMAX': 8.858850000000002, 'VMIN': 0.8437000000000001, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    33: {'R': 0.004256043581886279, 'VMAX': 12.3354, 'VMIN': 1.1748, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    34: {'R': 0.004628772449546381, 'VMAX': 11.3421, 'VMIN': 1.0802, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    35: {'R': 0.004605323754259924, 'VMAX': 11.399850000000002, 'VMIN': 1.0857, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    36: {'R': 0.004877097151775263, 'VMAX': 10.764600000000002, 'VMIN': 1.0252000000000001, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    37: {'R': 0.00515357658214801, 'VMAX': 10.187100000000001, 'VMIN': 0.9702000000000001, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    38: {'R': 0.0029689448370049287, 'VMAX': 17.683049999999998, 'VMIN': 1.6841, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
    39: {'R': 0.004170141784820684, 'VMAX': 12.589500000000001, 'VMIN': 1.199, 'T1': 0.05, 'T2': 1.0, 'T3': 2.1, 'Dt': 0.0},
}

# --- Fault design v2, derived from this network (see module docstring) ---
FAULT_GENS_39 = [30, 31, 38]
VRMIN_FRACTION_OF_VRMAX = 0.75
EXCITATION_RAMP_DURATION_S = 3 * (sum(GENROU_BY_BUS[b]['Td10'] for b in FAULT_GENS_39) / len(FAULT_GENS_39))

# Confirmed-connected topology weakening (see module docstring): removing
# both keeps all 39 buses mutually reachable (exhaustive per-bus BFS),
# largest avg-shortest-path increase (+46.5%) among all 562 safe pairs.
WEAKENING_LINES_39 = ["Line_9", "Line_26"]  # bus4-14, bus16-17

# v1's islanding pair, kept only as a named historical reference -- not
# used by this version's scenario. Present so anyone diffing history can
# see what changed and why (see module docstring's REDESIGN section).
_V1_ISLANDING_LINES_39 = ["Line_4", "Line_40"]  # bus2-25, bus25-26: fully islands bus 25 + gen 37


@dataclass
class ScenarioTimes39:
    contingency_t: float = 5.0     # corridor weakening + excitation ramp start, together
    horizon_t: float = 120.0       # longer than Kundur's 60s: this network's H values
                                    # (25-58s on real units) are far larger, dynamics are
                                    # inherently slower


def _build_base39():
    """Loads case39.m (MATPOWER import) and attaches GENROU+IEEEX1+TGOV1N
    to all 10 generators, parameters from ieee39_full.xlsx (see module
    docstring). Returns the un-setup system so fault devices can still be
    added."""
    ss = andes.load(CASE_PATH_STR, setup=False, no_output=True)
    gens = list(zip(ss.PV.idx.v, ss.PV.bus.v)) + list(zip(ss.Slack.idx.v, ss.Slack.bus.v))
    for gi, (gen_idx, bus) in enumerate(gens, start=1):
        bus = int(bus)
        gp = GENROU_BY_BUS[bus]
        ss.add('GENROU', dict(idx=f'GENROU_{gi}', bus=bus, gen=gen_idx, fn=FN_HZ, **gp))
        xp = IEEEX1_BY_BUS[bus]
        ss.add('IEEEX1', dict(idx=f'IEEEX1_{gi}', syn=f'GENROU_{gi}', **xp))
        tp = dict(TGOV1N_BY_BUS[bus])
        tp['VMIN'] = tp['VMIN'] * 0.5  # governor-floor fix, same pattern as Kundur's TGOV1
        ss.add('TGOV1N', dict(idx=f'TGOV1N_{gi}', syn=f'GENROU_{gi}', **tp))
    return ss


def _cache_vrmin_healthy_39(ss):
    """Stashes each fault generator's healthy VRMIN and its derived target
    on the system object, keyed by IEEEX1 device index."""
    genrou_bus = [int(b) for b in ss.GENROU.bus.v]
    genrou_idx = list(ss.GENROU.idx.v)
    ieeex1_syn = list(ss.IEEEX1.syn.v)
    fault_idx = []
    healthy = {}
    target = {}
    for bus in FAULT_GENS_39:
        gi = genrou_bus.index(bus)
        ix = ieeex1_syn.index(genrou_idx[gi])
        fault_idx.append(ix)
        healthy[ix] = ss.IEEEX1.VRMIN.v[ix]
        target[ix] = IEEEX1_BY_BUS[bus]['VRMAX'] * VRMIN_FRACTION_OF_VRMAX
    ss._excitation_fault_idx_39 = fault_idx
    ss._vrmin_healthy_39 = healthy
    ss._vrmin_target_39 = target
    return ss


def apply_excitation_ramp_39(ss, t: float, times: ScenarioTimes39, detection_t: float | None = None):
    """Tick-by-tick VRMIN ramp for the three fault generators (called from
    the run loop, same pattern as sim.kundur_system.apply_excitation_ramp)."""
    start = times.contingency_t
    dur = EXCITATION_RAMP_DURATION_S
    if detection_t is not None and t >= detection_t:
        fault_frac_at_detection = min(1.0, max(0.0, (detection_t - start) / dur))
        recovery_frac = min(1.0, (t - detection_t) / dur)
        frac = fault_frac_at_detection * (1.0 - recovery_frac)
    else:
        frac = min(1.0, max(0.0, (t - start) / dur))
    for ix in ss._excitation_fault_idx_39:
        healthy = ss._vrmin_healthy_39[ix]
        target = ss._vrmin_target_39[ix]
        ss.IEEEX1.VRMIN.v[ix] = healthy + frac * (target - healthy)


def build_ieee39_case(times: ScenarioTimes39 | None = None, apply_weakening: bool = True,
                       apply_excitation_fault: bool = True):
    """Flexible builder used for both the combined fault and the isolation
    counterfactuals: `apply_weakening` toggles the Line_9+Line_26 corridor
    thinning (confirmed connected, not an island) at contingency_t;
    `apply_excitation_fault` determines whether the run loop should be told
    to ramp VRMIN at all (the ramp itself is applied tick-by-tick by the
    caller via apply_excitation_ramp_39 -- if this flag is False, the
    caller simply never calls it, so VRMIN stays at its healthy value for
    the whole run). Always attaches GENROU+IEEEX1+TGOV1N to all 10
    generators regardless, since that's the network's dynamic baseline,
    not part of either fault."""
    times = times or ScenarioTimes39()
    ss = _build_base39()
    if apply_weakening:
        for line in WEAKENING_LINES_39:
            ss.add('Toggle', dict(model='Line', dev=line, t=times.contingency_t))
    ss.setup()
    _cache_vrmin_healthy_39(ss)
    ss._apply_excitation_fault_39 = apply_excitation_fault
    return ss, times


def build_uncorrected_39(times: ScenarioTimes39 | None = None):
    """The uncorrected timeline: a confirmed-connected corridor weakening
    (Line_9 + Line_26 tripped -- all 39 buses remain mutually reachable,
    verified by exhaustive BFS) at contingency_t, combined with the
    gradual VRMIN ramp on generators 30, 31, 38 (deliberately not adjacent
    to the weakened corridor and not structurally thin -- see module
    docstring) starting at the same time. No correction, no detector --
    this step only."""
    return build_ieee39_case(times, apply_weakening=True, apply_excitation_fault=True)
