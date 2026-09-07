"""
Phase 4: catalog of AURORA's corrective actions, decoupled from the ANDES
wiring in sim/kundur_system.py so the dashboard and report generator can
render human-readable explanations without importing the simulator.

Match explanations are mandatory in spirit here too: every action AURORA
takes is described in plain language, tied to the physical mechanism it
addresses, never as an opaque "AI intervened" black box.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionKind:
    key: str
    title: str
    mechanism: str
    real_world_analogue: str


CATALOG: dict[str, ActionKind] = {
    "reactive_redispatch": ActionKind(
        key="reactive_redispatch",
        title="Reactive-power redispatch",
        mechanism=(
            "De-energizes the excess capacitive surge in staged steps, restoring the "
            "generators' ability to absorb reactive power within their ±0.98 power-factor "
            "band instead of being driven outside it."
        ),
        real_world_analogue=(
            "Equivalent to the reactive-power compensation scheme the Spanish operator had "
            "proposed as early as July 2022 but had not yet put in force."
        ),
    ),
    "protection_retune": ActionKind(
        key="protection_retune",
        title="Adaptive protection re-tuning",
        mechanism=(
            "Cancels generation-trip events that were still in the future at the moment of "
            "detection, representing relay thresholds re-tuned so they no longer misfire on "
            "transient voltage excursions."
        ),
        real_world_analogue=(
            "Addresses the overly sensitive, inconsistent voltage-trip thresholds the ENTSO-E "
            "panel identified as the mechanism that turned a stressed-but-survivable grid into "
            "a cascading collapse."
        ),
    ),
    "storage_dispatch": ActionKind(
        key="storage_dispatch",
        title="Modeled storage dispatch",
        mechanism=(
            "Brings a modeled battery online at the point of detection to backstop the "
            "disturbance while the reactive correction takes effect."
        ),
        real_world_analogue=(
            "Stands in for fast-responding battery storage or demand response a real operator "
            "could dispatch in the same window."
        ),
    ),
}


def describe(action_key: str) -> ActionKind:
    return CATALOG[action_key]


def all_actions() -> list[ActionKind]:
    return list(CATALOG.values())
