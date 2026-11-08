from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import config


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path | None = None, readonly: bool = False) -> sqlite3.Connection:
    db_path = Path(path or config.DB_PATH)
    if readonly:
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def connection(path: Path | None = None, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    conn = connect(path=path, readonly=readonly)
    try:
        yield conn
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    schema = config.SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(street_stats)").fetchall()
    }
    for name, declaration in (
        ("lease_start_year", "INTEGER"),
        ("remaining_lease_years", "INTEGER"),
        ("lu_desc", "TEXT"),
        ("gpr", "TEXT"),
        ("height_control", "TEXT"),
        ("lha_class", "TEXT"),
        ("lha_name", "TEXT"),
        ("lha_type", "TEXT"),
        ("conservation_area", "TEXT"),
        ("cadastral_lot", "TEXT"),
        ("nearest_mrt_name", "TEXT"),
        ("nearest_mrt_exit", "TEXT"),
        ("nearest_mrt_distance_m", "REAL"),
        ("geo_updated_at", "TEXT"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE street_stats ADD COLUMN {name} {declaration}")
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def record_sync(
    conn: sqlite3.Connection,
    job: str,
    started_at: str,
    status: str,
    rows: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO sync_runs(job, started_at, finished_at, status, rows, error) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (job, started_at, now_iso(), status, rows, error),
    )
    conn.commit()


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "ura_transactions",
        "ura_rentals",
        "ura_planning",
        "street_stats",
        "watchlist",
        "due_diligence",
        "geo_layers",
    ]
    result: dict[str, int] = {}
    for table in tables:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        result[table] = int(row["n"]) if row else 0
    return result
