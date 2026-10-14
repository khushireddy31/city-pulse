"""Client and parsers for GBFS (General Bikeshare Feed Specification) feeds.

Handles both layouts in the wild:
  * v1.x / v2.x: feeds nested under a language key, epoch-int timestamps, plain-string names
  * v3.x: flat feed list, RFC 3339 timestamps, localized name arrays, "vehicles" naming
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

import httpx

T = TypeVar("T")


@dataclass(frozen=True)
class Station:
    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int | None


@dataclass(frozen=True)
class StationStatus:
    station_id: str
    reported_at: int
    bikes_available: int
    ebikes_available: int | None
    docks_available: int | None
    is_installed: bool
    is_renting: bool
    is_returning: bool


@dataclass(frozen=True)
class Snapshot(Generic[T]):
    last_updated: int
    ttl: int
    items: list[T]


def to_epoch(value: int | float | str) -> int:
    """GBFS v1/v2 use epoch seconds; v3 uses RFC 3339 strings."""
    if isinstance(value, int | float):
        return int(value)
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def discover_feeds(payload: dict[str, Any], language: str = "en") -> dict[str, str]:
    """Map feed name -> URL from a gbfs.json auto-discovery document."""
    data = payload["data"]
    if "feeds" in data:  # v3: no language nesting
        feeds = data["feeds"]
    else:
        lang = language if language in data else next(iter(data))
        feeds = data[lang]["feeds"]
    return {feed["name"]: feed["url"] for feed in feeds}


def _localized(value: str | list[dict[str, str]], language: str) -> str:
    if isinstance(value, str):
        return value
    for entry in value:
        if entry.get("language") == language:
            return entry["text"]
    return value[0]["text"]


def parse_station_information(payload: dict[str, Any], language: str = "en") -> Snapshot[Station]:
    stations = [
        Station(
            station_id=str(s["station_id"]),
            name=_localized(s["name"], language),
            lat=float(s["lat"]),
            lon=float(s["lon"]),
            capacity=s.get("capacity"),
        )
        for s in payload["data"]["stations"]
    ]
    return Snapshot(to_epoch(payload["last_updated"]), int(payload["ttl"]), stations)


def parse_station_status(payload: dict[str, Any]) -> Snapshot[StationStatus]:
    statuses = [
        StationStatus(
            station_id=str(s["station_id"]),
            reported_at=to_epoch(s["last_reported"]),
            bikes_available=int(s.get("num_bikes_available", s.get("num_vehicles_available", 0))),
            ebikes_available=s.get("num_ebikes_available"),
            docks_available=s.get("num_docks_available"),
            is_installed=bool(s.get("is_installed", True)),
            is_renting=bool(s.get("is_renting", True)),
            is_returning=bool(s.get("is_returning", True)),
        )
        for s in payload["data"]["stations"]
        if "last_reported" in s
    ]
    return Snapshot(to_epoch(payload["last_updated"]), int(payload["ttl"]), statuses)


class GBFSClient:
    def __init__(
        self,
        discovery_url: str,
        http: httpx.Client | None = None,
        language: str = "en",
    ) -> None:
        self.discovery_url = discovery_url
        self.language = language
        self._http = http or httpx.Client(timeout=15.0, follow_redirects=True)
        self._feeds: dict[str, str] | None = None

    def _get(self, url: str) -> dict[str, Any]:
        response = self._http.get(url)
        response.raise_for_status()
        return response.json()

    def feed_url(self, name: str) -> str:
        if self._feeds is None:
            self._feeds = discover_feeds(self._get(self.discovery_url), self.language)
        if name not in self._feeds:
            raise KeyError(f"feed {name!r} not published by {self.discovery_url}")
        return self._feeds[name]

    def station_information(self) -> Snapshot[Station]:
        return parse_station_information(self._get(self.feed_url("station_information")),
                                         self.language)

    def station_status(self) -> Snapshot[StationStatus]:
        return parse_station_status(self._get(self.feed_url("station_status")))
