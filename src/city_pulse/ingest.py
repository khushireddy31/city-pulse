"""Poll a GBFS system and store station snapshots.

    python -m city_pulse.ingest --once   # single poll (cron / CI friendly)
    python -m city_pulse.ingest          # loop forever, paced by the feed's own ttl
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from city_pulse import storage
from city_pulse.config import Settings
from city_pulse.gbfs import GBFSClient, StationStatus

log = logging.getLogger("city_pulse.ingest")

# Never poll faster than this, even if a feed advertises ttl=0.
MIN_POLL_INTERVAL_S = 15


@dataclass(frozen=True)
class RunResult:
    rows_seen: int
    rows_inserted: int
    rows_rejected: int
    ttl: int


def validate(
    statuses: list[StationStatus], feed_updated: int, max_report_age_s: int
) -> tuple[list[StationStatus], int]:
    """Drop rows that aren't live data: decommissioned stations, and stations whose last report
    is implausibly old relative to the feed (real feeds publish e.g. last_reported=86400)."""
    accepted = [
        s for s in statuses
        if s.is_installed and feed_updated - s.reported_at <= max_report_age_s
    ]
    return accepted, len(statuses) - len(accepted)


def run_once(
    client: GBFSClient,
    conn: sqlite3.Connection,
    settings: Settings,
    clock: Callable[[], float] = time.time,
) -> RunResult:
    run_id = storage.start_run(conn, int(clock()))
    try:
        info = client.station_information()
        status = client.station_status()
        now = int(clock())
        accepted, rejected = validate(status.items, status.last_updated, settings.max_report_age_s)
        storage.upsert_stations(conn, info.items, now)
        inserted = storage.insert_statuses(conn, accepted, now)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        storage.finish_run(conn, run_id, int(clock()), status="failed", error=repr(exc))
        raise
    storage.finish_run(
        conn, run_id, int(clock()), status="ok",
        rows_seen=len(status.items), rows_inserted=inserted, rows_rejected=rejected,
    )
    return RunResult(len(status.items), inserted, rejected, status.ttl)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    client = GBFSClient(settings.gbfs_url, language=settings.language)
    conn = storage.connect(settings.db_path)
    log.info("ingesting %s into %s", settings.gbfs_url, settings.db_path)

    while True:
        interval = MIN_POLL_INTERVAL_S
        try:
            result = run_once(client, conn, settings)
            interval = max(result.ttl, MIN_POLL_INTERVAL_S)
            log.info(
                "seen=%d inserted=%d rejected=%d",
                result.rows_seen, result.rows_inserted, result.rows_rejected,
            )
        except Exception:
            log.exception("ingest run failed")
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
