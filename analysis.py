"""Deeper analysis: trends, unusual spikes, daily patterns, metric correlation, fleet comparison."""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from .forecaster import load_series, THRESHOLDS

LABEL = {"cpu_usage": "CPU", "memory_usage": "Memory", "disk_latency_ms": "Disk delay", "temp_celsius": "Temperature"}


def analyze(server_id: str) -> dict:
    arrays, metrics, insights = {}, {}, []
    for m, thr in THRESHOLDS.items():
        ts, y = load_series(server_id, m)
        arrays[m] = y
        pad = np.pad(y, (12, 12), mode="edge")
        resid = y - np.median(sliding_window_view(pad, 25), axis=1)   # spike = far from local median
        z = resid / (resid.std() or 1e-9)
        idx = np.where(np.abs(z) > 3.5)[0]
        week = y[-2016:]
        slope = float(np.polyfit(np.arange(len(week)), week, 1)[0] * 288)   # change per day
        last = float(y[-1])
        dtl = round((thr - last) / slope, 1) if slope > 0.01 and last < thr else None
        hours = np.array([int(t[11:13]) for t in ts])
        recent = slice(-576, None)
        metrics[m] = {
            "label": LABEL[m], "threshold": thr, "now": round(last, 2), "average": round(float(y.mean()), 2),
            "highest": round(float(y.max()), 2), "typical_peak": round(float(np.percentile(y, 95)), 2),
            "change_per_day": round(slope, 2), "days_to_limit": dtl, "percent_of_limit": round(last / thr * 100, 1),
            "spikes_total": int(len(idx)), "spikes_48h": int(np.sum(idx >= len(y) - 576)),
            "hourly": [round(float(y[hours == h].mean()), 2) for h in range(24)],
            "recent": {"timestamps": ts[recent], "values": [round(float(v), 2) for v in y[recent]],
                       "spikes": [{"timestamp": ts[i], "value": round(float(y[i]), 2)} for i in idx if i >= len(y) - 576]},
        }
        if dtl is not None and dtl < 7:
            insights.append({"level": "bad" if dtl < 2 else "warn", "text": f"{LABEL[m]} is rising about {slope:.1f} per day. At this pace it reaches its limit in about {dtl} days."})
        if last / thr >= 0.9:
            insights.append({"level": "bad", "text": f"{LABEL[m]} is already at {last / thr * 100:.0f}% of its safe limit."})
        if metrics[m]["spikes_48h"]:
            insights.append({"level": "warn", "text": f"{LABEL[m]} had {metrics[m]['spikes_48h']} unusual spikes in the last 48 hours."})
    keys = list(THRESHOLDS)
    corr = np.nan_to_num(np.corrcoef(np.vstack([arrays[k] for k in keys])))
    for i in range(4):
        for j in range(i + 1, 4):
            if abs(corr[i][j]) > 0.6:
                insights.append({"level": "info", "text": f"{LABEL[keys[i]]} and {LABEL[keys[j]]} move {'together' if corr[i][j] > 0 else 'in opposite directions'} (strength {corr[i][j]:.2f})."})
    if not any(i["level"] != "info" for i in insights):
        insights.insert(0, {"level": "good", "text": "No problems found. All four measures look steady."})
    cpu = metrics["cpu_usage"]["hourly"]
    avg, h0 = min((sum(cpu[(h + i) % 24] for i in range(3)) / 3, h) for h in range(24))
    quiet = {"start_hour": h0, "end_hour": (h0 + 3) % 24, "avg_cpu": round(avg, 1)}
    insights.append({"level": "info", "text": f"Best time for maintenance: {h0:02d}:00 to {(h0 + 3) % 24:02d}:00, when CPU use is lowest (about {avg:.0f}%)."})
    return {"server_id": server_id, "metrics": metrics, "insights": insights, "quiet_window": quiet,
            "correlation": {"labels": [LABEL[k] for k in keys], "matrix": [[round(float(v), 2) for v in r] for r in corr]}}


def compare(metric: str, servers: list) -> dict:
    thr = THRESHOLDS[metric]
    out = {}
    for s in servers:
        ts, y = load_series(s, metric)
        out[s] = {"timestamps": ts[-288::3], "percent": [round(float(v) / thr * 100, 1) for v in y[-288::3]], "now": round(float(y[-1]), 2)}
    return {"metric": metric, "threshold": thr, "servers": out}
