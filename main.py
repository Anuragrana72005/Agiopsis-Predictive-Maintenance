"""AegisOps FastAPI application."""
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from . import analysis, database, forecaster, ticket_manager, telemetry_engine as te

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
lock = Lock()


def run_auto_ticketing() -> dict:
    """Scan every server/metric; open tickets for forecast breaches, refresh stale ones. Returns fleet health."""
    fleet = []
    for s in te.SERVERS:
        h = forecaster.server_health(s)
        for m in forecaster.THRESHOLDS:
            br = h["breaches"].get(m)
            if br:
                ticket_manager.create_if_needed(s, m, br)
            ticket_manager.refresh_open_tickets(s, m, br)
        fleet.append(h)
    return {"servers": fleet}


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    if database.telemetry_count() == 0:
        te.generate_history()
        run_auto_ticketing()
    yield


app = FastAPI(title="AegisOps Predictive Maintenance", lifespan=lifespan)


@app.get("/api/servers")
def servers():
    return run_auto_ticketing()


@app.get("/api/forecast/{server_id}")
def forecast(server_id: str, metric: str = "memory_usage", hours: int = Query(6, ge=2, le=24)):
    if server_id not in te.SERVERS:
        raise HTTPException(404, f"Unknown server '{server_id}'")
    if metric not in forecaster.THRESHOLDS:
        raise HTTPException(400, f"metric must be one of {list(forecaster.THRESHOLDS)}")
    try:
        return forecaster.full_forecast(server_id, metric, hours)
    except Exception as e:
        raise HTTPException(500, f"Forecast failed: {e}")


@app.post("/api/simulate/step")
def step(steps: int = Query(3, ge=1, le=288), live: bool = False):
    with lock:
        te.live_tick(steps, use_real=live)
        result = run_auto_ticketing()
    return {"advanced_minutes": steps * te.STEP_MIN, **result}


@app.post("/api/simulate/reset")
def reset():
    with lock:
        te.generate_history()
        forecaster._cache.clear()
        return run_auto_ticketing()


@app.get("/api/tickets")
def tickets(status: Optional[str] = None):
    return ticket_manager.list_tickets(status)


@app.post("/api/tickets/{ticket_id}/resolve")
def resolve(ticket_id: int):
    if not ticket_manager.set_status(ticket_id, "resolved"):
        raise HTTPException(404, "Ticket not found")
    return {"id": ticket_id, "status": "resolved"}


@app.post("/api/tickets/{ticket_id}/acknowledge")
def acknowledge(ticket_id: int):
    if not ticket_manager.set_status(ticket_id, "acknowledged"):
        raise HTTPException(404, "Ticket not found")
    return {"id": ticket_id, "status": "acknowledged"}


@app.get("/api/analysis/{server_id}")
def server_analysis(server_id: str):
    if server_id not in te.SERVERS:
        raise HTTPException(404, f"Unknown server '{server_id}'")
    return analysis.analyze(server_id)


@app.get("/api/compare")
def compare(metric: str = "memory_usage"):
    if metric not in forecaster.THRESHOLDS:
        raise HTTPException(400, f"metric must be one of {list(forecaster.THRESHOLDS)}")
    return analysis.compare(metric, te.SERVERS)


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
