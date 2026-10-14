import httpx
import pytest

from city_pulse import storage
from city_pulse.gbfs import GBFSClient
from city_pulse.ingest import run_once

from .conftest import BASE, FEED_UPDATED, ROUTES, mock_http


def test_rejects_decommissioned_and_stale_rows(client, settings):
    conn = storage.connect(settings.db_path)
    result = run_once(client, conn, settings, clock=lambda: FEED_UPDATED)
    assert (result.rows_seen, result.rows_inserted, result.rows_rejected) == (3, 2, 1)
    ids = {r["station_id"] for r in conn.execute("SELECT station_id FROM latest_status")}
    assert ids == {"a", "b"}


def test_reingesting_same_feed_is_idempotent(client, settings):
    conn = storage.connect(settings.db_path)
    run_once(client, conn, settings, clock=lambda: FEED_UPDATED)
    second = run_once(client, conn, settings, clock=lambda: FEED_UPDATED + 60)
    assert second.rows_inserted == 0
    assert conn.execute("SELECT COUNT(*) FROM status_snapshots").fetchone()[0] == 2


def test_failed_run_is_recorded_and_raised(settings):
    routes = {k: v for k, v in ROUTES.items() if not k.endswith("station_status.json")}
    broken = GBFSClient(f"{BASE}/gbfs.json", http=mock_http(routes))
    conn = storage.connect(settings.db_path)
    with pytest.raises(httpx.HTTPStatusError):
        run_once(broken, conn, settings, clock=lambda: FEED_UPDATED)
    run = conn.execute("SELECT status, error FROM ingest_runs").fetchone()
    assert run["status"] == "failed" and "404" in run["error"]
    assert conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0] == 0
