"""Marine Institute live wave-buoy readings (data.marine.ie ERDDAP).

Legitimate open data — the offshore Irish Weather Buoys measure REAL conditions,
a ground-truth counterpart to the forecast. We surface the latest reading from
the west-coast buoys (M3 SW approaches, M6 deep Atlantic) as a "measured now"
panel. Cached like forecasts; failures degrade gracefully (panel just hides).
"""

from __future__ import annotations

import time

from . import openmeteo

ERDDAP = "https://erddap.marine.ie/erddap/tabledap/IWBNetwork.json"

# West-coast buoys worth showing (id -> friendly label + rough location).
BUOYS = [
    ("M6", "M6 — deep Atlantic (~15°W)"),
    ("M3", "M3 — SW approaches (off Kerry)"),
    ("M2", "M2 — east/Irish Sea"),
]

_cache: dict | None = None
_cache_ts: float = 0.0
_TTL_S = 1800  # 30 min; buoys report roughly hourly


def _latest(station: str) -> dict | None:
    """Latest measured reading for one buoy, or None."""
    q = (f'{ERDDAP}?time,WaveHeight,WavePeriod,MeanWaveDirection,SeaTemperature'
         f'&station_id=%22{station}%22&orderByMax(%22time%22)')
    try:
        payload = openmeteo._get(q)  # reuse the resilient httpx client
        rows = payload["table"]["rows"]
        if not rows:
            return None
        t, hs, tp, mdir, sst = rows[0]
        return {
            "station": station,
            "time": t,
            "wave_height_m": hs,
            "wave_period_s": tp,
            "wave_dir_deg": mdir,
            "sea_temp_c": sst,
        }
    except Exception:  # noqa: BLE001
        return None


def latest_readings(force: bool = False) -> list[dict]:
    """Cached list of latest buoy readings (only buoys that returned data)."""
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache is not None and (now - _cache_ts) < _TTL_S:
        return _cache
    readings = []
    for station, label in BUOYS:
        r = _latest(station)
        if r:
            r["label"] = label
            readings.append(r)
    _cache = readings
    _cache_ts = now
    return readings
