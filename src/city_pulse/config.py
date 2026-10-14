"""Runtime settings, read from environment variables so nothing city-specific is hardcoded."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Citi Bike (NYC) is only the default; point CITY_PULSE_GBFS_URL at any system's gbfs.json.
DEFAULT_GBFS_URL = "https://gbfs.citibikenyc.com/gbfs/gbfs.json"


@dataclass(frozen=True)
class Settings:
    gbfs_url: str = DEFAULT_GBFS_URL
    db_path: Path = Path("data/city_pulse.db")
    language: str = "en"
    # Status rows reported longer ago than this are treated as dead stations, not live data.
    max_report_age_s: int = 7 * 24 * 3600
    # /health reports "stale" when the last successful ingest is older than this.
    stale_after_s: int = 300

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            gbfs_url=os.getenv("CITY_PULSE_GBFS_URL", defaults.gbfs_url),
            db_path=Path(os.getenv("CITY_PULSE_DB", str(defaults.db_path))),
            language=os.getenv("CITY_PULSE_LANGUAGE", defaults.language),
            max_report_age_s=int(
                os.getenv("CITY_PULSE_MAX_REPORT_AGE_S", defaults.max_report_age_s)
            ),
            stale_after_s=int(os.getenv("CITY_PULSE_STALE_AFTER_S", defaults.stale_after_s)),
        )
