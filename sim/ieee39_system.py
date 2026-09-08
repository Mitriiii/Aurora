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

NOTE: the New England 39-bus system is natively a 60 Hz system (it is the
North American New England/New York interconnection benchmark), unlike the
50 Hz framing used for the Kundur-based Spain scenario. GENCLS is
configured with fn=60 to match the actual system, not forced to 50 Hz.
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
    30: dict(Sn=1040.0, H=43.680, D=0.0, ra=0.0001346153846153846, xd1=0.02981),
    31: dict(Sn=836.0,  H=25.331, D=0.0, ra=0.003229665071770335,  xd1=0.08337),
    32: dict(Sn=843.7,  H=30.204, D=0.0, ra=0.00045750859310181346, xd1=0.06294),
    33: dict(Sn=1174.8, H=33.599, D=0.0, ra=0.00018896833503575077, xd1=0.03711),
    34: dict(Sn=1080.2, H=28.085, D=0.0, ra=0.00012960562858729864, xd1=0.12220),
    35: dict(Sn=1085.7, H=37.782, D=0.0, ra=0.0056645482177397075,  xd1=0.04605),
    36: dict(Sn=1025.2, H=27.065, D=0.0, ra=0.00026141240733515414, xd1=0.04780),
    37: dict(Sn=970.2,  H=23.576, D=0.0, ra=0.0007070707070707071,  xd1=0.05875),
    38: dict(Sn=1684.1, H=58.101, D=0.0, ra=0.00017813669022029573, xd1=0.03385),
    39: dict(Sn=1199.0, H=599.500, D=0.0, ra=8.340283569641367e-05, xd1=0.00500),
}

FN_HZ = 60.0  # New England system is natively 60 Hz, not forced to 50 Hz


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
