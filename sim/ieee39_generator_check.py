"""
Verifies the case39.m <-> ieee39_full.xlsx generator correspondence is
matched by BUS NUMBER, not row/index order, and checks that case39.m's own
dispatched MW does not exceed the (borrowed) Sn rating at a reasonable
power factor. Load and dispatch throughout come from case39.m ONLY --
ieee39_full.xlsx is used solely as the source of H/Sn/ra/xd1 dynamics
parameters (see sim/ieee39_system.py's module docstring for why).

Run: python -m sim.ieee39_generator_check
"""
from __future__ import annotations

import andes

from sim.ieee39_system import CASE_PATH, GENERATOR_DYNAMICS_BY_BUS

ASSUMED_REASONABLE_PF = 0.85  # typical generator design PF; flags dispatch that would
                              # require an implausibly low PF to fit under Sn


def main():
    andes.config_logger(stream_level=30)

    # --- Independently re-derive the bus-keyed table from ieee39_full.xlsx,
    #     from scratch, to confirm GENERATOR_DYNAMICS_BY_BUS wasn't
    #     accidentally built from row order. ---
    ss_dyn = andes.load(andes.get_case('ieee39/ieee39_full.xlsx'), setup=True, no_output=True)
    rederived = {}
    for i, idx in enumerate(ss_dyn.GENROU.idx.v):
        bus = int(ss_dyn.GENROU.bus.v[i])
        rederived[bus] = dict(
            Sn=ss_dyn.GENROU.Sn.v[i], H=ss_dyn.GENROU.M.v[i] / 2,
            ra=ss_dyn.GENROU.ra.v[i], xd1=ss_dyn.GENROU.xd1.v[i],
        )
    assert set(rederived.keys()) == set(GENERATOR_DYNAMICS_BY_BUS.keys()), \
        "bus sets differ between re-derivation and the module's stored table"
    for bus, vals in rederived.items():
        stored = GENERATOR_DYNAMICS_BY_BUS[bus]
        for k in ('Sn', 'H', 'ra', 'xd1'):
            rel_err = abs(vals[k] - stored[k]) / max(abs(vals[k]), 1e-12)
            assert rel_err < 1e-9, \
                f"bus {bus} field {k} mismatch: stored={stored[k]} re-derived={vals[k]} (rel_err={rel_err:.2e})"
    print("Independent re-derivation from ieee39_full.xlsx matches the stored "
          "GENERATOR_DYNAMICS_BY_BUS table exactly, confirmed by bus number.\n")

    # --- Load case39.m (load/dispatch source of truth) and build the
    #     explicit mapping table by bus. PFlow must run first: PV.p/Slack.p
    #     read as 0.0 immediately after import (populated by the solve). ---
    ss = andes.load(str(CASE_PATH), setup=True, no_output=True)
    ss.PFlow.run()
    assert ss.PFlow.converged, "case39.m power flow did not converge"

    rows = []
    for idx, bus, p in zip(ss.PV.idx.v, ss.PV.bus.v, ss.PV.p.v):
        rows.append((int(bus), idx, 'PV', float(p)))
    for idx, bus, p in zip(ss.Slack.idx.v, ss.Slack.bus.v, ss.Slack.p.v):
        rows.append((int(bus), idx, 'Slack', float(p)))
    rows.sort(key=lambda r: r[0])

    print(f"{'bus':>4} {'case39.m gen idx':>16} {'type':>6} {'P disp (p.u.)':>14} "
          f"{'P disp (MW)':>12} {'Sn (MVA)':>9} {'H (s)':>8} {'xd1 (p.u.)':>10} "
          f"{'ra (p.u.)':>10} {'P/Sn @ 1.0 PF':>13}")
    flags = []
    for bus, gidx, gtype, p_pu in rows:
        params = GENERATOR_DYNAMICS_BY_BUS[bus]
        p_mw = p_pu * ss.config.mva  # case39.m system base MVA
        p_over_sn = p_mw / params['Sn']
        reasonable_max_mw = params['Sn'] * ASSUMED_REASONABLE_PF
        flag = ""
        if p_mw > reasonable_max_mw:
            flag = " <-- FLAG: exceeds Sn * assumed PF (%.2f)" % ASSUMED_REASONABLE_PF
            flags.append((bus, gidx, p_mw, params['Sn'], reasonable_max_mw))
        print(f"{bus:>4} {gidx!s:>16} {gtype:>6} {p_pu:>14.4f} {p_mw:>12.2f} "
              f"{params['Sn']:>9.1f} {params['H']:>8.3f} {params['xd1']:>10.5f} "
              f"{params['ra']:>10.6f} {p_over_sn:>13.4f}{flag}")

    print()
    print(f"System base MVA (case39.m): {ss.config.mva}")
    print(f"Total case39.m dispatch: {sum(r[3] for r in rows) * ss.config.mva:.1f} MW "
          f"(load/dispatch is from case39.m only, not ieee39_full.xlsx)")

    if flags:
        print(f"\n{len(flags)} generator(s) FAIL the P <= Sn*{ASSUMED_REASONABLE_PF} check:")
        for bus, gidx, p_mw, sn, reasonable_max in flags:
            implied_pf = p_mw / sn
            print(f"  bus {bus} (gen {gidx}): P={p_mw:.1f} MW vs Sn={sn:.1f} MVA "
                  f"-> would need PF >= {implied_pf:.3f} to fit, "
                  f"reasonable ceiling at PF={ASSUMED_REASONABLE_PF} is {reasonable_max:.1f} MW")
            print(f"    PROPOSED FIX: this generator's Sn from ieee39_full.xlsx is too low for "
                  f"case39.m's own (higher-total-load) dispatch. Do not silently rescale Sn without "
                  f"a cited source -- either (a) source this generator's own Sn from a rating that "
                  f"covers case39.m's dispatch (e.g., MATPOWER's own case39.m gen.mBase field, if "
                  f"present, or the unit's Pmax with a stated PF), or (b) flag this generator's "
                  f"dynamics as unverified pending a consistent rating.")
    else:
        print(f"\nAll {len(rows)} generators PASS: dispatched MW stays within Sn*{ASSUMED_REASONABLE_PF} "
              f"(reasonable power factor) using case39.m's own dispatch.")


if __name__ == "__main__":
    main()
