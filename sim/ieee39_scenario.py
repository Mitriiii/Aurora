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

GENERATOR SELECTION: the three lowest-inertia REAL generators (H, in
seconds, from GENROU.M/2), excluding bus 39:
    bus 37: H=23.58   (lowest)
    bus 31: H=25.33   (2nd -- also the power-flow slack bus, but per
                        case39.m's own comment this is "nuke01", a real
                        plant; its slack role is a power-flow solving
                        convenience, not a reason to exclude it once
                        GENROU dynamics are attached)
    bus 36: H=27.07   (3rd)
(next-lowest excluded: bus 34 at H=28.09, bus 32 at H=30.20)

FAULT MAGNITUDES -- DERIVED FROM THIS NETWORK, NOT KUNDUR'S NUMBERS:
  - VRMIN ramp target per generator = 0.75 * that generator's own VRMAX
    (a documented fraction of its physical ceiling, not a copied absolute
    value): bus37 -> 3.75, bus31 -> 3.90, bus36 -> 4.875. Each is well
    above that generator's natural steady-state exciter output (vout ~=
    1.03/0.98/1.06 p.u. respectively, confirmed by a short TDS run before
    committing to these targets), so the ramp genuinely binds once complete.
  - Ramp duration = 3 * mean(Td10) of the three fault generators (Td10 is
    each unit's own transient open-circuit field time constant -- a real
    physical timescale of the exciter/field, not an arbitrary pacing
    choice): mean(6.70, 6.56, 5.66) = 6.307s -> 3x = 18.92s.

N-2 CONTINGENCY -- STRUCTURAL, NOT ARBITRARY: this network has NO parallel
line circuits anywhere (checked explicitly: zero duplicate bus-pairs among
all 46 lines), unlike Kundur's three parallel tie lines. Each generator
connects to the 345kV mesh via a single radial line, so losing that one
line would simply island the generator -- not a meaningful "tie
weakening." Bus 25 (which feeds generator 37, the primary/lowest-H fault
target) has exactly two mesh connections besides its generator tie:
Line_4 (bus 2-25) and Line_40 (bus 25-26). Losing both is a real N-2 that
isolates bus 25 (and generator 37) from the rest of the 345kV network --
directly relevant to the selected fault target, not picked for convenience.

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

# --- Fault design, derived from this network (see module docstring) ---
FAULT_GENS_39 = [37, 31, 36]
VRMIN_FRACTION_OF_VRMAX = 0.75
EXCITATION_RAMP_DURATION_S = 3 * (sum(GENROU_BY_BUS[b]['Td10'] for b in FAULT_GENS_39) / len(FAULT_GENS_39))
TIE_LOSS_LINES_39 = ["Line_4", "Line_40"]  # bus2-25, bus25-26: isolates bus 25 (-> gen 37)


@dataclass
class ScenarioTimes39:
    contingency_t: float = 5.0     # N-2 tie loss + excitation ramp start, together
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


def build_uncorrected_39(times: ScenarioTimes39 | None = None):
    """The uncorrected timeline: sustained N-2 tie-line loss (Line_4 +
    Line_40, isolating bus 25 / generator 37) at contingency_t, combined
    with the gradual VRMIN ramp on generators 37, 31, 36 starting at the
    same time. No correction, no detector -- this step only."""
    times = times or ScenarioTimes39()
    ss = _build_base39()
    for line in TIE_LOSS_LINES_39:
        ss.add('Toggle', dict(model='Line', dev=line, t=times.contingency_t))
    ss.setup()
    _cache_vrmin_healthy_39(ss)
    return ss, times
