"""Holt-Winters + lag-feature regression forecasters, evaluation, health score and TTF."""
import warnings
from datetime import datetime, timedelta
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .database import get_conn

THRESHOLDS = {"cpu_usage": 88.0, "memory_usage": 90.0, "disk_latency_ms": 85.0, "temp_celsius": 82.0}
SEASON, STEP_MIN, TEST_STEPS = 288, 5, 144
HW_WINDOW, ML_WINDOW = 4 * SEASON, 7 * SEASON
_cache: dict = {}


def load_series(server_id: str, metric: str):
    if metric not in THRESHOLDS:
        raise ValueError(f"Unknown metric '{metric}'")
    with get_conn() as c:
        rows = c.execute(f"SELECT timestamp, {metric} FROM telemetry WHERE server_id=? ORDER BY id", (server_id,)).fetchall()
    return [r[0] for r in rows], np.array([r[1] for r in rows], dtype=float)


# ---------- Model 1: Holt-Winters ----------
def hw_forecast(y: np.ndarray, steps: int):
    """Returns (mean, status). Falls back gracefully if seasonal fit fails."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    y = y[-HW_WINDOW:]
    y = np.convolve(np.pad(y, (5, 0), mode='edge'), np.ones(6) / 6, mode='valid')  # denoise before fitting
    attempts = [("seasonal", dict(trend="add", seasonal="add", seasonal_periods=SEASON, initialization_method="heuristic")),
                ("damped-trend (no seasonality)", dict(trend="add", damped_trend=True, initialization_method="estimated"))]
    for name, kw in attempts:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fc = ExponentialSmoothing(y, **kw).fit(optimized=True).forecast(steps)
            if np.all(np.isfinite(fc)):
                return np.asarray(fc), "ok" if name == "seasonal" else f"fallback: {name}"
        except Exception:
            continue
    # last resort: seasonal-naive repeat of the previous day
    reps = int(np.ceil(steps / SEASON))
    return np.tile(y[-SEASON:], reps)[:steps], "fallback: seasonal-naive"


# ---------- Model 2: lag-feature regression ----------
def _row(buf: np.ndarray, i: int, tod: float) -> list:
    l1 = buf[i - 1]
    return [l1, buf[i - 2], buf[i - 3], buf[i - 6], buf[i - 12], buf[i - SEASON], l1 - buf[i - 12],
            buf[i - 12:i].mean(), buf[i - 72:i].mean(), buf[i - 12:i].std(),
            np.sin(2 * np.pi * tod), np.cos(2 * np.pi * tod)]


def _tod(ts: datetime) -> float:
    return (ts.hour * 60 + ts.minute) / 1440


def lag_forecast(y: np.ndarray, last_ts: datetime, steps: int):
    y = y[-ML_WINDOW:]
    n = len(y)
    start = last_ts - timedelta(minutes=STEP_MIN * (n - 1))
    X = [_row(y, i, _tod(start + timedelta(minutes=STEP_MIN * i))) for i in range(SEASON, n)]
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(np.array(X), y[SEASON:])
    buf = np.concatenate([y, np.zeros(steps)])
    for j in range(steps):  # recursive multi-step forecast
        ts = last_ts + timedelta(minutes=STEP_MIN * (j + 1))
        buf[n + j] = model.predict(np.array([_row(buf, n + j, _tod(ts))]))[0]
    return buf[n:]


def _metrics(actual, pred):
    err = actual - pred
    ss_tot = float(np.sum((actual - actual.mean()) ** 2)) or 1e-9
    mae = float(np.mean(np.abs(err)))
    return {"mae": round(mae, 3), "rmse": round(float(np.sqrt(np.mean(err ** 2))), 3),
            "r2": round(1 - float(np.sum(err ** 2)) / ss_tot, 3),
            "accuracy_pct": round(max(0.0, 100 * (1 - mae / max(float(np.mean(np.abs(actual))), 1e-9))), 2)}


def _breach(ts_list, mean, threshold):
    idx = np.where(mean > threshold)[0]
    if len(idx) == 0:
        return None
    i = int(idx[0])
    return {"timestamp": ts_list[i], "hours_until_breach": round((i + 1) * STEP_MIN / 60, 2)}


def full_forecast(server_id: str, metric: str, hours: int):
    hours = max(2, min(24, int(hours)))
    steps = hours * 12
    ts, y = load_series(server_id, metric)
    key = ("full", server_id, metric, hours, ts[-1])
    if key in _cache:
        return _cache[key]
    last = datetime.fromisoformat(ts[-1])
    # Evaluation: train on everything but the last 12h, score against the hold-out
    y_tr, y_te = y[:-TEST_STEPS], y[-TEST_STEPS:]
    tr_last = last - timedelta(minutes=STEP_MIN * TEST_STEPS)
    hw_ev, hw_status = hw_forecast(y_tr, TEST_STEPS)
    ml_ev = lag_forecast(y_tr, tr_last, TEST_STEPS)
    ev = {"holt_winters": _metrics(y_te, hw_ev), "lag_regression": _metrics(y_te, ml_ev)}
    best = "holt_winters" if ev["holt_winters"]["rmse"] <= ev["lag_regression"]["rmse"] else "lag_regression"
    # Final fit on all data
    hw_fc, hw_status = hw_forecast(y, steps)
    ml_fc = lag_forecast(y, last, steps)
    f_ts = [(last + timedelta(minutes=STEP_MIN * (i + 1))).isoformat() for i in range(steps)]
    means = {"holt_winters": hw_fc, "lag_regression": ml_fc}
    sigma = max(ev[best]["rmse"], 1e-3)
    widen = 1.96 * sigma * np.sqrt(1 + np.arange(1, steps + 1) / 72)  # uncertainty grows with horizon
    thr = THRESHOLDS[metric]
    out = {"server_id": server_id, "metric": metric, "hours": hours, "threshold": thr,
           "history": {"timestamps": ts[-576:], "values": [round(v, 3) for v in y[-576:]]},
           "forecast": {"timestamps": f_ts, "holt_winters": [round(v, 3) for v in hw_fc],
                        "lag_regression": [round(v, 3) for v in ml_fc], "best_model": best,
                        "ci_lower": [round(v, 3) for v in means[best] - widen],
                        "ci_upper": [round(v, 3) for v in means[best] + widen]},
           "evaluation": ev, "holt_winters_status": hw_status, "test_window_hours": TEST_STEPS * STEP_MIN / 60,
           "breach": _breach(f_ts, means[best], thr)}
    _cache[key] = out
    return out


def quick_breach(server_id: str, metric: str, hours: int = 24):
    """Fast breach scan used for fleet status and auto-ticketing (lag-regression model)."""
    ts, y = load_series(server_id, metric)
    key = ("quick", server_id, metric, hours, ts[-1])
    if key not in _cache:
        steps = hours * 12
        fc = lag_forecast(y, datetime.fromisoformat(ts[-1]), steps)
        f_ts = [(datetime.fromisoformat(ts[-1]) + timedelta(minutes=STEP_MIN * (i + 1))).isoformat() for i in range(steps)]
        _cache[key] = (float(y[-1]), _breach(f_ts, fc, THRESHOLDS[metric]))
    if len(_cache) > 400:
        _cache.clear()
    return _cache[key]


def server_health(server_id: str):
    """Health score 0-100, status, per-metric breach info and overall TTF (hours)."""
    current, breaches, pens = {}, {}, []
    for m, thr in THRESHOLDS.items():
        cur, br = quick_breach(server_id, m)
        current[m] = round(cur, 2)
        pen = 60 * float(np.clip((cur / thr - 0.55) / 0.45, 0, 1))
        if br:
            breaches[m] = br
            pen += 35 * (1 - br["hours_until_breach"] / 24)
        pens.append(pen)
    pens.sort(reverse=True)
    score = int(round(max(0, 100 - min(100, pens[0] + 0.25 * sum(pens[1:])))))
    ttf = min((b["hours_until_breach"] for b in breaches.values()), default=None)
    status = "CRITICAL" if score < 50 or (ttf is not None and ttf < 6) else "WARNING" if score < 80 or ttf is not None else "HEALTHY"
    return {"server_id": server_id, "health_score": score, "status": status, "current": current,
            "ttf_hours": ttf, "breaches": breaches}
