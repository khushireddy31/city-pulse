from __future__ import annotations

import httpx
import pytest

from city_pulse.config import Settings
from city_pulse.gbfs import GBFSClient

FEED_UPDATED = 1_792_010_000
BASE = "https://example.test/gbfs"

DISCOVERY_V1 = {
    "last_updated": FEED_UPDATED,
    "ttl": 60,
    "data": {
        "en": {
            "feeds": [
                {"name": "station_information", "url": f"{BASE}/station_information.json"},
                {"name": "station_status", "url": f"{BASE}/station_status.json"},
            ]
        }
    },
}

STATION_INFORMATION = {
    "last_updated": FEED_UPDATED,
    "ttl": 60,
    "data": {
        "stations": [
            {"station_id": "a", "name": "Broadway & W 60 St", "lat": 40.77, "lon": -73.98,
             "capacity": 30},
            {"station_id": "b", "name": "Brook Ave & E 141 St", "lat": 40.81, "lon": -73.92,
             "capacity": 20},
            {"station_id": "dead", "name": "Decommissioned", "lat": 40.0, "lon": -73.0,
             "capacity": 0},
        ]
    },
}

STATION_STATUS = {
    "last_updated": FEED_UPDATED,
    "ttl": 60,
    "data": {
        "stations": [
            {"station_id": "a", "num_bikes_available": 0, "num_ebikes_available": 0,
             "num_docks_available": 30, "is_installed": 1, "is_renting": 1, "is_returning": 1,
             "last_reported": FEED_UPDATED - 30},
            {"station_id": "b", "num_bikes_available": 20, "num_ebikes_available": 4,
             "num_docks_available": 0, "is_installed": 1, "is_renting": 1, "is_returning": 1,
             "last_reported": FEED_UPDATED - 10},
            # Shape copied from a real Citi Bike row: uninstalled, last_reported in 1970.
            {"station_id": "dead", "num_bikes_available": 0, "num_docks_available": 0,
             "is_installed": 0, "is_renting": 0, "is_returning": 0, "last_reported": 86400},
        ]
    },
}

ROUTES = {
    f"{BASE}/gbfs.json": DISCOVERY_V1,
    f"{BASE}/station_information.json": STATION_INFORMATION,
    f"{BASE}/station_status.json": STATION_STATUS,
}


def mock_http(routes: dict[str, dict]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = routes.get(str(request.url))
        return httpx.Response(200, json=payload) if payload else httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def client() -> GBFSClient:
    return GBFSClient(f"{BASE}/gbfs.json", http=mock_http(ROUTES))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(gbfs_url=f"{BASE}/gbfs.json", db_path=tmp_path / "test.db")
