import time

import pytest
from fastapi.testclient import TestClient

from city_pulse import storage
from city_pulse.api import create_app
from city_pulse.ingest import run_once


@pytest.fixture
def api(settings):
    return TestClient(create_app(settings))


def test_health_without_data_is_503(api):
    response = api.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "no_data"


@pytest.fixture
def ingested(client, settings):
    conn = storage.connect(settings.db_path)
    run_once(client, conn, settings, clock=time.time)
    conn.close()


def test_health_ok_after_ingest(api, ingested):
    response = api.get("/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"


def test_summary(api, ingested):
    assert api.get("/summary").json() == {
        "stations": 2, "bikes_available": 20, "ebikes_available": 4,
        "empty_stations": 1, "full_stations": 1,
    }


def test_empty_and_full(api, ingested):
    assert [s["station_id"] for s in api.get("/stations/empty").json()] == ["a"]
    assert [s["station_id"] for s in api.get("/stations/full").json()] == ["b"]


def test_history_unknown_station_404(api, ingested):
    assert api.get("/stations/nope/history").status_code == 404
