"""
Phase 5: FastAPI + WebSocket backend. Streams a precomputed scenario run
(see sim/run_scenario.py) to the dashboard at a controllable playback pace.

Precompute-then-replay, not live-drive-ANDES-per-websocket-tick, is a
deliberate choice: the detection and correction are genuinely computed
tick-by-tick with no hindsight (sim/run_scenario.py), but decoupling
solver performance from UI pacing makes the demo reliable at any playback
speed the presenter wants (Section 3 of the build brief explicitly allows
running the sim clock faster or slower than real time).

Guardrail: every response is labeled SIMULATED or PUBLIC HISTORICAL/LIVE
DATA. This server has no connection to any real grid control system.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim.run_scenario import run_full_scenario, RUNS_DIR
from reports.report_generator import generate_report
from data.entsoe_client import get_spain_snapshot

WEB_DIR = ROOT / "web"

app = FastAPI(title="AURORA Grid Stability Intelligence (SIMULATION)")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_run_lock = asyncio.Lock()


def _load_latest() -> dict | None:
    path = RUNS_DIR / "latest.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "SIMULATION"}


@app.post("/api/run")
async def trigger_run():
    async with _run_lock:
        result = await asyncio.get_event_loop().run_in_executor(None, run_full_scenario)
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUNS_DIR / "latest.json", "w") as f:
            json.dump(result, f)
    u = result["uncorrected"]
    return JSONResponse({
        "detection_t": u["detection_t"],
        "lead_time_to_first_trip_s": u["lead_time_to_first_trip_s"],
        "lead_time_to_collapse_s": u["lead_time_to_collapse_s"],
        "collapse_t": u["collapse_t"],
        "corrected_collapse_t": (result["corrected"] or {}).get("collapse_t"),
    })


@app.get("/api/run/latest")
async def get_latest_run():
    result = _load_latest()
    if result is None:
        return JSONResponse({"error": "no run yet -- POST /api/run first"}, status_code=404)
    return JSONResponse(result)


@app.get("/api/report/latest")
async def get_latest_report():
    result = _load_latest()
    if result is None:
        return PlainTextResponse("No run yet.", status_code=404)
    return PlainTextResponse(generate_report(result))


@app.get("/api/entsoe/spain-today")
async def entsoe_today():
    """Credibility layer (Section 4.3 / 2.6): real Spanish generation mix,
    quietly alongside the simulation. Clearly labeled; returns an honest
    'offline' status if no API token is configured rather than fabricating
    data."""
    return JSONResponse(await get_spain_snapshot())


@app.websocket("/ws/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("cmd") != "play":
                continue

            speed = float(msg.get("speed", 4.0))
            result = _load_latest()
            if result is None:
                await ws.send_json({"type": "error", "message": "no run available"})
                continue

            dt = result["dt"]
            u_frames = result["uncorrected"]["frames"]
            c_frames = (result["corrected"] or {}).get("frames", [])
            n = max(len(u_frames), len(c_frames))

            await ws.send_json({
                "type": "meta",
                "dt": dt,
                "scenario_times": result["scenario_times"],
                "detection_t": result["uncorrected"]["detection_t"],
                "detection_reasons": result["uncorrected"]["detection_reasons"],
                "collapse_t": result["uncorrected"]["collapse_t"],
                "corrected_collapse_t": (result["corrected"] or {}).get("collapse_t"),
                "actions_taken": (result["corrected"] or {}).get("actions_taken", []),
                "n_frames": n,
            })

            frame_period = dt / max(speed, 0.01)
            for i in range(n):
                uf = u_frames[i] if i < len(u_frames) else u_frames[-1]
                cf = c_frames[i] if i < len(c_frames) else (c_frames[-1] if c_frames else None)
                await ws.send_json({"type": "tick", "i": i, "uncorrected": uf, "corrected": cf})
                await asyncio.sleep(frame_period)

            await ws.send_json({"type": "done"})
    except WebSocketDisconnect:
        return


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
