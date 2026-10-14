from city_pulse.gbfs import discover_feeds, parse_station_status, to_epoch

from .conftest import DISCOVERY_V1, STATION_STATUS


def test_discover_v1_falls_back_to_first_language():
    feeds = discover_feeds(DISCOVERY_V1, language="fr")
    assert set(feeds) == {"station_information", "station_status"}


def test_discover_v3_flat_layout():
    payload = {"data": {"feeds": [{"name": "station_status", "url": "https://x/ss.json"}]}}
    assert discover_feeds(payload) == {"station_status": "https://x/ss.json"}


def test_to_epoch_accepts_int_and_rfc3339():
    assert to_epoch(1_700_000_000) == 1_700_000_000
    assert to_epoch("2023-11-14T22:13:20Z") == 1_700_000_000
    assert to_epoch("2023-11-14T23:13:20+01:00") == 1_700_000_000


def test_parse_status_v1():
    snap = parse_station_status(STATION_STATUS)
    assert snap.ttl == 60
    a = next(s for s in snap.items if s.station_id == "a")
    assert a.bikes_available == 0 and a.docks_available == 30 and a.is_renting


def test_parse_status_v3_vehicle_naming():
    payload = {
        "last_updated": "2023-11-14T22:13:20Z",
        "ttl": 30,
        "data": {"stations": [{
            "station_id": "z", "num_vehicles_available": 7, "num_docks_available": 3,
            "is_installed": True, "is_renting": True, "is_returning": False,
            "last_reported": "2023-11-14T22:13:00Z",
        }]},
    }
    (z,) = parse_station_status(payload).items
    assert z.bikes_available == 7 and not z.is_returning and z.reported_at == 1_699_999_980


def test_client_discovers_and_fetches(client):
    info = client.station_information()
    assert [s.name for s in info.items][:2] == ["Broadway & W 60 St", "Brook Ave & E 141 St"]
