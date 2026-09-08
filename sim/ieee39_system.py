"""
Phase 7 (early): loads the IEEE 39-bus New England system via ANDES's
MATPOWER format support, per BUILD_PROMPT.md Section 4.1's stated import
path.

case39.m is pulled from MATPOWER's own GitHub repository (not the Texas
A&M registration-gated source):
    https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case39.m
saved to data/cases/case39.m.

IMPORTANT, checked explicitly (this is exactly what got missed with the
Kundur case): raw MATPOWER format carries ONLY static power-flow data --
buses, generators as PV/Slack, branches. It has no dynamic generator
models and cannot express a Toggle/disturbance event at all. Confirmed by
inspection: `ss.Toggle.n == 0` and `ss.GENROU.n == ss.GENCLS.n == 0`
immediately after import. There is no hidden baked-in event to disable
here, unlike kundur_full.xlsx's stock Line_8 trip -- there is simply
nothing dynamic in the file at all.

To run a time-domain simulation at all, minimal generator dynamics have to
be added. We use GENCLS (the classical model -- constant EMF behind
transient reactance, second-order swing equation, no AVR or governor) so
this stays a genuine "does TDS work on this network" check, not a preview
of a fault-mechanism design. Its H (inertia), Sn (MVA rating), ra (armature
resistance), and xd1 (transient reactance) are NOT invented -- they are
read from ANDES's own bundled `ieee39_full.xlsx`, itself an implementation
of the same widely-published New England 39-bus 10-generator dynamic
dataset, cross-checked to confirm the generator-to-bus mapping is
identical between the two files (buses 30-39 in both). Total system load
differs slightly between the two sources (~62.5 p.u. in case39.m's own
MATPOWER dispatch vs ~58.6 p.u. in ieee39_full.xlsx) -- these are two real,
independently-published parameterizations of "the" IEEE 39-bus system, not
byte-identical, and that difference is reported rather than hidden.

FREQUENCY: the New England 39-bus system is natively a 60 Hz benchmark (it
is the North American New England/New York interconnection), but this
project's subject is the Spanish (50 Hz) grid, so the system is run at
50 Hz nominal -- explicitly, not by accident. Confirmed from ANDES's own
source (andes/system/config_runtime.py): `system.config.freq` is a
case-level default (60) used for case-relevant bookkeeping, but the
electromechanical dynamics themselves are driven by each generator's own
`fn` NumParam, per andes/models/synchronous/genbase.py:
    delta' = (2*pi*fn) * (omega - 1)          [rotor angle]
    M * omega' = tm - te - D*(omega - 1)      [rotor speed, M = 2H]
Both `system.config.freq` AND each GENCLS's `fn` are set to 50 here, since
`fn` is what actually appears in the equations. H, xd', ra are per-unit
physical quantities and are frequency-label-independent -- only the
delta/omega coupling changes. This has a real, checkable consequence:
linearizing the swing equation for a machine against the rest of the
system (Ks = synchronizing power coefficient, treated as unchanged by the
fn relabeling since it comes from per-unit network reactances) gives
natural oscillation frequency
    f_osc = (1 / 2*pi) * sqrt(2*pi*fn*Ks / M) = sqrt(fn*Ks / (4*pi*H))
i.e. f_osc scales with sqrt(fn) for fixed H and Ks. Going from 60->50 Hz
predicts f_osc(50)/f_osc(60) = sqrt(50/60) = 0.9129 -- verified numerically
in sim/ieee39_verification_kick.py against the same kick run at both
frequencies.
"""
from __future__ import annotations

from pathlib import Path

import andes

CASE_PATH = Path(__file__).resolve().parent.parent / "data" / "cases" / "case39.m"

# H (p.u.-s), Sn (MVA), ra (p.u.), xd1 (p.u.) by generator bus, read from
# ANDES's bundled andes.get_case('ieee39/ieee39_full.xlsx') GENROU models.
# This is the standard, widely-published New England 39-bus dynamic
# dataset -- not invented, and cited here explicitly.
GENERATOR_DYNAMICS_BY_BUS = {
    30: dict(Sn=1040.0, H=43.68000000000001,  D=0.0, ra=0.0001346153846153846,  xd1=0.02980769230769231),
    31: dict(Sn=836.0,  H=25.330799999999996, D=0.0, ra=0.003229665071770335,   xd1=0.0833732057416268),
    32: dict(Sn=843.7,  H=30.204460000000005, D=0.0, ra=0.00045750859310181346, xd1=0.06293706293706294),
    33: dict(Sn=1174.8, H=33.59927999999999,  D=0.0, ra=0.00018896833503575077, xd1=0.037112700034048346),
    34: dict(Sn=1080.2, H=28.0852,            D=0.0, ra=0.00012960562858729864, xd1=0.12219959266802445),
    35: dict(Sn=1085.7, H=37.782360000000004, D=0.0, ra=0.0056645482177397075,  xd1=0.04605323754259925),
    36: dict(Sn=1025.2, H=27.06528,           D=0.0, ra=0.00026141240733515414, xd1=0.04779555208739758),
    37: dict(Sn=970.2,  H=23.575860000000002, D=0.0, ra=0.0007070707070707071,  xd1=0.05875077303648732),
    38: dict(Sn=1684.1, H=58.10144999999999,  D=0.0, ra=0.00017813669022029573, xd1=0.03384597114185618),
    39: dict(Sn=1199.0, H=599.5,              D=0.0, ra=8.340283569641367e-05,  xd1=0.0050041701417848205),
}

FN_HZ = 50.0  # Explicitly set to match this project's subject (Spain), not the
              # New England system's native 60 Hz. See module docstring.


def load_case39_matpower(with_dynamics: bool = True):
    """Loads case39.m via ANDES's MATPOWER importer. If `with_dynamics`,
    attaches a GENCLS classical model to every PV/Slack generator using the
    cited standard dataset above -- the minimum needed for TDS to be
    meaningful, nothing more (no AVR, no governor, no fault mechanism)."""
    if not CASE_PATH.exists():
        raise FileNotFoundError(
            f"{CASE_PATH} not found -- fetch it from "
            "https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case39.m"
        )

    ss = andes.load(str(CASE_PATH), setup=False, no_output=True)
    ss.config.freq = FN_HZ  # case-level bookkeeping value; see docstring for why
                            # this alone does NOT drive the dynamics

    if with_dynamics:
        gens = list(zip(ss.PV.idx.v, ss.PV.bus.v)) + list(zip(ss.Slack.idx.v, ss.Slack.bus.v))
        for gi, (gen_idx, bus) in enumerate(gens, start=1):
            params = GENERATOR_DYNAMICS_BY_BUS[int(bus)]
            ss.add('GENCLS', dict(
                idx=f'GENCLS_{gi}', bus=bus, gen=gen_idx,
                Sn=params['Sn'], Vn=345.0, fn=FN_HZ,
                D=params['D'], M=2 * params['H'],
                ra=params['ra'], xd1=params['xd1'],
            ))

    ss.setup()
    return ss
