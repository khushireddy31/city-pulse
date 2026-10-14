"""Read API over the ingested data.

    uvicorn city_pulse.api:app --reload
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response

from city_pulse import storage
from city_pulse.config import Settings

STATION_COLUMNS = """
    st.station_id, st.name, st.lat, st.lon, st.capacity,
    ls.bikes_available, ls.ebikes_available, ls.docks_available, ls.reported_at
"""


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = storage.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


DB = Annotated[sqlite3.Connection, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=500)]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="City Pulse", version="0.1.0")
    app.state.settings = settings

    @app.get("/health")
    def health(response: Response, conn: DB) -> dict:
        row = conn.execute(
            "SELECT MAX(finished_at) AS t FROM ingest_runs WHERE status = 'ok'"
        ).fetchone()
        if row["t"] is None:
            response.status_code = 503
            return {"status": "no_data", "last_ingest_at": None, "age_s": None}
        age = int(time.time()) - row["t"]
        stale = age > settings.stale_after_s
        if stale:
            response.status_code = 503
        return {"status": "stale" if stale else "ok", "last_ingest_at": row["t"], "age_s": age}

    @app.get("/summary")
    def summary(conn: DB) -> dict:
        row = conn.execute(
            """
            SELECT COUNT(*)                                   AS stations,
                   COALESCE(SUM(bikes_available), 0)          AS bikes_available,
                   COALESCE(SUM(ebikes_available), 0)         AS ebikes_available,
                   COALESCE(SUM(bikes_available = 0), 0)      AS empty_stations,
                   COALESCE(SUM(docks_available = 0), 0)      AS full_stations
            FROM latest_status
            WHERE is_renting = 1
            """
        ).fetchone()
        return dict(row)

    @app.get("/stations/empty")
    def empty_stations(
        conn: DB, limit: Limit = 50
    ) -> list[dict]:
        rows = conn.execute(
            f"""
            SELECT {STATION_COLUMNS}
            FROM latest_status ls JOIN stations st USING (station_id)
            WHERE ls.is_renting = 1 AND ls.bikes_available = 0
            ORDER BY st.capacity DESC NULLS LAST
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/stations/full")
    def full_stations(
        conn: DB, limit: Limit = 50
    ) -> list[dict]:
        rows = conn.execute(
            f"""
            SELECT {STATION_COLUMNS}
            FROM latest_status ls JOIN stations st USING (station_id)
            WHERE ls.is_returning = 1 AND ls.docks_available = 0
            ORDER BY st.capacity DESC NULLS LAST
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/stations/{station_id}/history")
    def station_history(
        station_id: str,
        conn: DB,
        hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
    ) -> dict:
        station = conn.execute(
            "SELECT * FROM stations WHERE station_id = ?", (station_id,)
        ).fetchone()
        if station is None:
            raise HTTPException(404, f"unknown station {station_id}")
        since = int(time.time()) - hours * 3600
        rows = conn.execute(
            """
            SELECT reported_at, bikes_available, ebikes_available, docks_available
            FROM status_snapshots
            WHERE station_id = ? AND reported_at >= ?
            ORDER BY reported_at
            """,
            (station_id, since),
        ).fetchall()
        return {"station": dict(station), "history": [dict(r) for r in rows]}

    return app


app = create_app()
