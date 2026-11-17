"""SQLite persistence layer (data/cluster_telemetry.db)."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cluster_telemetry.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    server_id TEXT NOT NULL,
    cpu_usage REAL, memory_usage REAL, disk_latency_ms REAL, temp_celsius REAL
);
CREATE INDEX IF NOT EXISTS idx_tel_server_ts ON telemetry(server_id, timestamp);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL, metric TEXT NOT NULL,
    predicted_breach_time TEXT, hours_until_breach REAL,
    severity TEXT, recommended_action TEXT,
    status TEXT DEFAULT 'open', created_at TEXT
);
"""


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as c:
        c.executescript(SCHEMA)


def telemetry_count() -> int:
    with get_conn() as c:
        return c.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]


def clear_all():
    with get_conn() as c:
        c.executescript("DELETE FROM telemetry; DELETE FROM tickets; DELETE FROM sqlite_sequence;")
