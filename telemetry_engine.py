"""Synthetic telemetry generator, live-tick simulator and optional psutil reader."""
from datetime import datetime, timedelta
import numpy as np
from .database import get_conn, clear_all

SERVERS = ["SRV-WEB-01", "SRV-DB-01", "SRV-AI-01", "SRV-CACHE-01"]
METRICS = ["cpu_usage", "memory_usage", "disk_latency_ms", "temp_celsius"]
STEP_MIN = 5
DAY_STEPS = 288
HIST_STEPS = 14 * DAY_STEPS
_rng = np.random.default_rng()


def _daily(ts: datetime) -> float:
    """24h sinusoidal traffic seasonality in [-1, 1], peaking mid-afternoon."""
    h = ts.hour + ts.minute / 60
    return float(np.sin(2 * np.pi * (h - 9) / 24))


def _point(server: str, k: int, ts: datetime) -> dict:
    """Metrics for server at global step k (0 = start of history)."""
    d, p, n = _daily(ts), k / HIST_STEPS, _rng.normal
    if server == "SRV-WEB-01":      # healthy
        v = (40 + 12 * d + n(0, 2.5), 46 + 4 * d + n(0, 1.2), 7 + 2 * d + n(0, 0.8), 52 + 3 * d + n(0, 0.8))
    elif server == "SRV-DB-01":     # gradual memory leak toward 95%
        v = (38 + 10 * d + n(0, 2.5), 44 + 44 * p + 2 * d + n(0, 0.7), 14 + 4 * d + n(0, 1.2), 55 + 4 * d + n(0, 0.8))
    elif server == "SRV-AI-01":     # thermal + CPU degradation
        v = (50 + 24 * p ** 1.3 + 9 * d + n(0, 2.5), 62 + 3 * d + n(0, 1.0), 9 + 2 * d + n(0, 0.8),
             58 + 18 * p ** 1.4 + 3 * d + n(0, 0.9))
    else:                           # SRV-CACHE-01: periodic disk I/O spikes every 6h, growing
        spike = (45 + 40 * p) * np.exp(-((k % 72) / 2.5)) if k % 72 < 12 else 0
        v = (35 + 9 * d + n(0, 2.5), 58 + 3 * d + n(0, 1.0), 12 + 4 * d + spike + n(0, 1.2), 50 + 3 * d + n(0, 0.8))
    cpu, mem, dsk, tmp = (float(x) for x in v)
    return {"cpu_usage": float(np.clip(cpu, 1, 100)), "memory_usage": float(np.clip(mem, 1, 99.5)),
            "disk_latency_ms": max(0.5, dsk), "temp_celsius": max(20.0, tmp)}


def _insert(rows):
    with get_conn() as c:
        c.executemany("INSERT INTO telemetry (timestamp, server_id, cpu_usage, memory_usage, disk_latency_ms, temp_celsius) "
                      "VALUES (?,?,?,?,?,?)", rows)


def generate_history():
    """Regenerate 14 days of 5-minute telemetry for all servers (ending now)."""
    clear_all()
    end = datetime.now().replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % STEP_MIN)
    start = end - timedelta(minutes=STEP_MIN * (HIST_STEPS - 1))
    rows = []
    for s in SERVERS:
        for k in range(HIST_STEPS):
            ts = start + timedelta(minutes=STEP_MIN * k)
            m = _point(s, k, ts)
            rows.append((ts.isoformat(), s, m["cpu_usage"], m["memory_usage"], m["disk_latency_ms"], m["temp_celsius"]))
    _insert(rows)


def _real_metrics() -> dict:
    import psutil
    temp = None
    try:
        for entries in (psutil.sensors_temperatures() or {}).values():
            if entries:
                temp = entries[0].current
                break
    except Exception:
        pass
    lat = 5.0
    try:
        io = psutil.disk_io_counters()
        ops = io.read_count + io.write_count
        lat = max(0.5, (io.read_time + io.write_time) / ops) if ops else 5.0
    except Exception:
        pass
    return {"cpu_usage": psutil.cpu_percent(interval=0.2), "memory_usage": psutil.virtual_memory().percent,
            "disk_latency_ms": float(lat), "temp_celsius": float(temp) if temp is not None else 55.0}


def live_tick(steps: int = 3, use_real: bool = False):
    """Advance the cluster clock by `steps` x 5 minutes. With use_real=True, SRV-WEB-01 reads host metrics via psutil."""
    with get_conn() as c:
        rows = []
        for s in SERVERS:
            r = c.execute("SELECT timestamp FROM telemetry WHERE server_id=? ORDER BY id DESC LIMIT 1", (s,)).fetchone()
            cnt = c.execute("SELECT COUNT(*) FROM telemetry WHERE server_id=?", (s,)).fetchone()[0]
            last = datetime.fromisoformat(r[0])
            for i in range(1, steps + 1):
                ts = last + timedelta(minutes=STEP_MIN * i)
                m = _point(s, cnt - 1 + i, ts)
                if use_real and s == "SRV-WEB-01":
                    try:
                        m = _real_metrics()
                    except Exception:
                        pass  # psutil unavailable -> keep simulated values
                rows.append((ts.isoformat(), s, m["cpu_usage"], m["memory_usage"], m["disk_latency_ms"], m["temp_celsius"]))
    _insert(rows)
