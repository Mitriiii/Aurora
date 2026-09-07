"""
Phase 7 credibility layer (Section 4.3): pulls Spain's real generation mix
from the ENTSO-E Transparency Platform to show quietly alongside the
simulation ("today's actual Spanish generation mix" ticker).

This never blocks the core simulation/detection/correction pipeline (Phases
1-3 do not depend on it). Requires an ENTSOE_API_KEY environment variable,
obtained by registering at the ENTSO-E Transparency Platform and emailing
transparency@entsoe.eu with subject "Restful API access". Without a key,
this returns an honest "offline" status -- never fabricated data. The
dashboard must label this PUBLIC HISTORICAL/LIVE DATA, distinct from the
SIMULATED model output.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta


async def get_spain_snapshot() -> dict:
    api_key = os.environ.get("ENTSOE_API_KEY")
    if not api_key:
        return {
            "status": "offline",
            "source": "ENTSO-E Transparency Platform",
            "label": "PUBLIC HISTORICAL/LIVE DATA",
            "message": (
                "No ENTSOE_API_KEY configured. Register at the ENTSO-E Transparency "
                "Platform and email transparency@entsoe.eu (subject: 'Restful API access') "
                "to enable this credibility ticker."
            ),
        }

    try:
        import pandas as pd
        from entsoe import EntsoePandasClient
    except ImportError:
        return {
            "status": "offline",
            "source": "ENTSO-E Transparency Platform",
            "label": "PUBLIC HISTORICAL/LIVE DATA",
            "message": "entsoe-py not installed. `pip install entsoe-py pandas` to enable.",
        }

    try:
        client = EntsoePandasClient(api_key=api_key)
        now = pd.Timestamp.now(tz="Europe/Madrid")
        start = now - pd.Timedelta(hours=3)
        generation = client.query_generation("ES", start=start, end=now)
        latest = generation.iloc[-1]
        by_source = {str(k): float(v) for k, v in latest.items() if v == v}  # drop NaN
        return {
            "status": "ok",
            "source": "ENTSO-E Transparency Platform",
            "label": "PUBLIC HISTORICAL/LIVE DATA",
            "as_of": str(generation.index[-1]),
            "generation_mw_by_source": by_source,
        }
    except Exception as e:
        return {
            "status": "error",
            "source": "ENTSO-E Transparency Platform",
            "label": "PUBLIC HISTORICAL/LIVE DATA",
            "message": f"ENTSO-E query failed: {e}",
        }
