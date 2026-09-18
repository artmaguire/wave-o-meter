"""Spot metadata loading and typed access.

Reads data/spots.json (the confirmed 10 west-coast spots) and exposes typed
Spot objects, ordered by county per SDD §11 (Clare first).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

from . import config


@dataclass(frozen=True)
class Spot:
    id: str
    name: str
    county: str
    lat: float
    lon: float
    break_type: str          # beach | reef | point
    skill: str               # beginner | intermediate | advanced
    optimal_swell_dir: tuple[float, float]
    optimal_wind_dir: tuple[float, float]
    swell_height_m: tuple[float, float]
    tide: str                # low | mid | high | any | range e.g. "low-mid"
    hazards: str = ""
    notes: str = ""
    aka: str | None = None
    orientation_verified: bool = False
    links: dict[str, str] = field(default_factory=dict)
    profile: dict[str, str] = field(default_factory=dict)

    @property
    def is_reef(self) -> bool:
        """Reef-like: picky about swell direction, period and tide.

        Point breaks over reef (e.g. Easkey Right) behave like reefs for
        scoring purposes — far fussier than a forgiving sand beach.
        """
        return self.break_type in ("reef", "point")

    @property
    def display_name(self) -> str:
        return f"{self.name} / {self.aka}" if self.aka else self.name


def _to_spot(raw: dict) -> Spot:
    return Spot(
        id=raw["id"],
        name=raw["name"],
        county=raw["county"],
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        break_type=raw["break_type"],
        skill=raw["skill"],
        optimal_swell_dir=tuple(raw["optimal_swell_dir"]),
        optimal_wind_dir=tuple(raw["optimal_wind_dir"]),
        swell_height_m=tuple(raw["swell_height_m"]),
        tide=raw["tide"],
        hazards=raw.get("hazards", ""),
        notes=raw.get("notes", ""),
        aka=raw.get("aka"),
        orientation_verified=bool(raw.get("orientation_verified", False)),
        links=raw.get("links", {}),
        profile=raw.get("profile", {}),
    )


def _county_key(county: str) -> int:
    try:
        return config.COUNTY_ORDER.index(county)
    except ValueError:
        return len(config.COUNTY_ORDER)  # unknown counties sort last


@lru_cache(maxsize=1)
def load_spots() -> list[Spot]:
    """Load and cache spots, ordered by county (Clare first) then name."""
    with open(config.SPOTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    spots = [_to_spot(s) for s in data["spots"]]
    spots.sort(key=lambda s: (_county_key(s.county), s.name))
    return spots


def spots_by_id() -> dict[str, Spot]:
    return {s.id: s for s in load_spots()}


def get_spot(spot_id: str) -> Spot | None:
    return spots_by_id().get(spot_id)
