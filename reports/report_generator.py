"""
Phase 6: forensic auto-report. Turns a completed run (data/runs/latest.json)
into a one-page Markdown incident report -- the plain-English executive
summary an ENTSO-E-style investigation takes months to produce, generated
in the time it takes to run the scenario.
"""
from __future__ import annotations

import json
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
REPORTS_DIR = Path(__file__).resolve().parent


def generate_report(result: dict) -> str:
    u = result["uncorrected"]
    c = result["corrected"]
    times = result["scenario_times"]

    lines = []
    lines.append("# AURORA Incident Report")
    lines.append("")
    lines.append("**SIMULATION ONLY.** All figures below come from a synthetic time-domain "
                  "simulation seeded with the physical parameters of the 28 April 2025 Iberian "
                  "blackout. Nothing here is connected to, or derived from, a real control system.")
    lines.append("")
    lines.append(f"Generated: {result['generated_at']}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    if u["detection_t"] is not None:
        lines.append(
            f"AURORA's detector flagged a developing fragile-regime signature at "
            f"**t={u['detection_t']:.1f}s**, **{u['lead_time_to_first_trip_s']:.1f}s before** "
            f"the first scripted generation trip (t={times['trip_1_t']:.1f}s) and "
            f"**{u['lead_time_to_collapse_s']:.1f}s before** the uncorrected branch's total "
            f"collapse (t={u['collapse_t']:.1f}s)."
        )
    else:
        lines.append("The detector did not fire during this run.")
    lines.append("")

    lines.append("## What was detected, and when")
    lines.append("")
    lines.append("| Time | Event |")
    lines.append("|---|---|")
    lines.append(f"| t={times['line_kick_t']:.1f}s | Precursor tie-line disturbance (kicks off the inter-area oscillation) |")
    lines.append(f"| t={times['surge_on_t']:.1f}s | Reactive-power surge onset (excess capacitive charging, unabsorbed) |")
    if u["detection_t"] is not None:
        lines.append(f"| **t={u['detection_t']:.1f}s** | **AURORA danger flag fires** |")
    lines.append(f"| t={times['trip_1_t']:.1f}s | First generation trip (historical: ~317 MW) |")
    lines.append(f"| t={times['trip_2_t']:.1f}s | Second generation trip (historical: ~730 MW) |")
    lines.append(f"| t={times['trip_3_t']:.1f}s | Third generation trip (historical: ~550 MW) |")
    if u["collapse_t"] is not None:
        lines.append(f"| t={u['collapse_t']:.1f}s | **Uncorrected branch: total system collapse** |")
    lines.append("")

    lines.append("## Why the detector fired")
    lines.append("")
    for r in (u["detection_reasons"] or []):
        lines.append(f"- {r}")
    lines.append("")

    lines.append("## Corrective action taken (AURORA-corrected branch)")
    lines.append("")
    if c:
        for a in c["actions_taken"]:
            lines.append(f"- {a}")
        lines.append("")
        outcome = "survived without collapse" if c["collapse_t"] is None else f"still collapsed at t={c['collapse_t']:.1f}s"
        lines.append(f"**Outcome: the corrected branch {outcome}.**")
    else:
        lines.append("No corrective branch was run (detector did not fire).")
    lines.append("")

    lines.append("## Outcome comparison")
    lines.append("")
    lines.append("| | Uncorrected (what happened) | AURORA-corrected |")
    lines.append("|---|---|---|")
    lines.append(f"| Collapse | {'t=' + format(u['collapse_t'], '.1f') + 's' if u['collapse_t'] else 'none'} "
                  f"| {'t=' + format(c['collapse_t'], '.1f') + 's' if c and c['collapse_t'] else 'none'} |")
    lines.append(f"| Generation trips | 3 of 3 fired | "
                  f"{sum(1 for a in (c['actions_taken'] if c else []) if 'already in progress' in a)} of 3 fired |")
    lines.append("")

    lines.append("## Model disclosure")
    lines.append("")
    lines.append("- Network: ANDES built-in Kundur two-area, four-machine benchmark system "
                  "(not a network model of Spain).")
    lines.append("- Detection: rule-based threshold detector on reactive-power margin drift and "
                  "oscillation growth rate (Phase 3 of the build plan) -- no machine learning in this MVP.")
    lines.append("- All absolute MW/kV figures are illustrative; the mechanism (voltage rising "
                  "while frequency falls, growing oscillation, cascading trips) is the modeled fidelity target.")
    lines.append("")

    return "\n".join(lines)


def main():
    path = RUNS_DIR / "latest.json"
    with open(path) as f:
        result = json.load(f)
    report = generate_report(result)
    out_path = REPORTS_DIR / "latest_report.md"
    with open(out_path, "w") as f:
        f.write(report)
    print(report)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
