"""SQLite storage. Snapshots are keyed on (station_id, reported_at), so re-ingesting the same
feed is idempotent: a station that hasn't reported since the last poll adds no rows."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from city_pulse.gbfs import Station, StationStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    station_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    capacity    INTEGER,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS status_snapshots (
    station_id        TEXT NOT NULL,
    reported_at       INTEGER NOT NULL,
    fetched_at        INTEGER NOT NULL,
    bikes_available   INTEGER NOT NULL,
    ebikes_available  INTEGER,
    docks_available   INTEGER,
    is_renting        INTEGER NOT NULL,
    is_returning      INTEGER NOT NULL,
    PRIMARY KEY (station_id, reported_at)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      INTEGER NOT NULL,
    finished_at     INTEGER,
    status          TEXT NOT NULL,       -- running | ok | failed
    rows_seen       INTEGER,
    rows_inserted   INTEGER,
    rows_rejected   INTEGER,
    error           TEXT
);

CREATE VIEW IF NOT EXISTS latest_status AS
SELECT s.*
FROM status_snapshots s
JOIN (
    SELECT station_id, MAX(reported_at) AS reported_at
    FROM status_snapshots
    GROUP BY station_id
) latest USING (station_id, reported_at);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # lets the API read while ingest writes
    conn.executescript(SCHEMA)
    return conn


def upsert_stations(conn: sqlite3.Connection, stations: Iterable[Station], now: int) -> None:
    conn.executemany(
        """
        INSERT INTO stations (station_id, name, lat, lon, capacity, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (station_id) DO UPDATE SET
            name = excluded.name, lat = excluded.lat, lon = excluded.lon,
            capacity = excluded.capacity, updated_at = excluded.updated_at
        """,
        [(s.station_id, s.name, s.lat, s.lon, s.capacity, now) for s in stations],
    )


def insert_statuses(
    conn: sqlite3.Connection, statuses: Iterable[StationStatus], fetched_at: int
) -> int:
    """Insert snapshots, skipping ones already stored. Returns the number of new rows."""
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO status_snapshots (
            station_id, reported_at, fetched_at, bikes_available, ebikes_available,
            docks_available, is_renting, is_returning
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (s.station_id, s.reported_at, fetched_at, s.bikes_available, s.ebikes_available,
             s.docks_available, int(s.is_renting), int(s.is_returning))
            for s in statuses
        ],
    )
    return conn.total_changes - before


def start_run(conn: sqlite3.Connection, now: int) -> int:
    cur = conn.execute(
        "INSERT INTO ingest_runs (started_at, status) VALUES (?, 'running')", (now,)
    )
    conn.commit()
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    now: int,
    *,
    status: str,
    rows_seen: int | None = None,
    rows_inserted: int | None = None,
    rows_rejected: int | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE ingest_runs
        SET finished_at = ?, status = ?, rows_seen = ?, rows_inserted = ?,
            rows_rejected = ?, error = ?
        WHERE id = ?
        """,
        (now, status, rows_seen, rows_inserted, rows_rejected, error, run_id),
    )
    conn.commit()
