"""
Phase 7 credibility layer (Section 4.3): Red Electrica's ESIOS platform for
granular Spain-specific indicators (e.g. real-time national demand).

Requires an ESIOS_API_KEY environment variable, obtained by emailing
consultasios@ree.es. Not used by the core simulation/detection/correction
pipeline. Returns an honest "offline" status without a key -- never
fabricated data.
"""
from __future__ import annotations

import os
import json
from urllib.request import Request, urlopen
from urllib.error import URLError

ESIOS_BASE = "https://api.esios.ree.es"
NATIONAL_DEMAND_INDICATOR = 1293


async def get_national_demand() -> dict:
    api_key = os.environ.get("ESIOS_API_KEY")
    if not api_key:
        return {
            "status": "offline",
            "source": "REE ESIOS",
            "label": "PUBLIC HISTORICAL/LIVE DATA",
            "message": (
                "No ESIOS_API_KEY configured. Request a personal token by emailing "
                "consultasios@ree.es to enable this credibility ticker."
            ),
        }

    try:
        req = Request(
            f"{ESIOS_BASE}/indicators/{NATIONAL_DEMAND_INDICATOR}",
            headers={
                "Accept": "application/json; application/vnd.esios-api-v2+json",
                "x-api-key": api_key,
            },
        )
        with urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read())
        values = payload.get("indicator", {}).get("values", [])
        latest = values[-1] if values else None
        return {
            "status": "ok",
            "source": "REE ESIOS",
            "label": "PUBLIC HISTORICAL/LIVE DATA",
            "latest": latest,
        }
    except (URLError, Exception) as e:
        return {
            "status": "error",
            "source": "REE ESIOS",
            "label": "PUBLIC HISTORICAL/LIVE DATA",
            "message": f"ESIOS query failed: {e}",
        }
