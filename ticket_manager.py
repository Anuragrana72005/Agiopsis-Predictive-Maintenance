"""Predictive maintenance ticket creation and lifecycle."""
from datetime import datetime
from typing import Optional
from .database import get_conn

ACTIONS = {
    "memory_usage": "Memory leak suspected: capture heap dump, restart leaking service in a maintenance window, schedule patch/rollback.",
    "cpu_usage": "Sustained CPU growth: rebalance workloads, scale out nodes, throttle batch jobs and profile hot processes.",
    "disk_latency_ms": "Disk I/O saturation: move cache persistence to NVMe, stagger flush/snapshot jobs, check SMART health.",
    "temp_celsius": "Thermal risk: inspect fans/airflow and heatsinks, re-paste or replace cooling, shift load to a cooler node.",
}


def _severity(hours: float) -> str:
    return "critical" if hours < 6 else "high" if hours < 12 else "medium"


def create_if_needed(server_id: str, metric: str, breach: dict) -> bool:
    """Create a ticket unless an open/acknowledged one exists for the same server + metric."""
    with get_conn() as c:
        dup = c.execute("SELECT 1 FROM tickets WHERE server_id=? AND metric=? AND status IN ('open','acknowledged')",
                        (server_id, metric)).fetchone()
        if dup:
            return False
        c.execute("INSERT INTO tickets (server_id, metric, predicted_breach_time, hours_until_breach, severity, "
                  "recommended_action, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (server_id, metric, breach["timestamp"], breach["hours_until_breach"], _severity(breach["hours_until_breach"]),
                   ACTIONS[metric], "open", datetime.now().isoformat(timespec="seconds")))
        return True


def refresh_open_tickets(server_id: str, metric: str, breach: Optional[dict]):
    """Keep hours-remaining current on open tickets; close them if the breach is no longer forecast."""
    with get_conn() as c:
        if breach:
            c.execute("UPDATE tickets SET predicted_breach_time=?, hours_until_breach=?, severity=? "
                      "WHERE server_id=? AND metric=? AND status IN ('open','acknowledged')",
                      (breach["timestamp"], breach["hours_until_breach"], _severity(breach["hours_until_breach"]), server_id, metric))
        else:
            c.execute("UPDATE tickets SET status='resolved' WHERE server_id=? AND metric=? AND status IN ('open','acknowledged')",
                      (server_id, metric))


def list_tickets(status: Optional[str] = None):
    with get_conn() as c:
        q = "SELECT * FROM tickets" + (" WHERE status=?" if status else "") + " ORDER BY (status='resolved'), hours_until_breach"
        return [dict(r) for r in c.execute(q, (status,) if status else ())]


def set_status(ticket_id: int, status: str) -> bool:
    with get_conn() as c:
        return c.execute("UPDATE tickets SET status=? WHERE id=?", (status, ticket_id)).rowcount > 0
