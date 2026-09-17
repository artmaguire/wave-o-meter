"""Forecast orchestration (SDD 5, 6, 8, 10).

Ties the pieces together: fetch raw data -> classify tide -> score each hour ->
compute confidence -> build the JSON payloads the API serves, and cache them.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from . import cache, confidence, config, dayparts, openmeteo, scoring, summary as summary_mod
from . import tide as tide_mod
from .spots import Spot, get_spot, load_spots

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg: float | None) -> str | None:
    if deg is None:
        return None
    return _COMPASS[round(deg / 22.5) % 16]


def _wind_relation(wind_from: float, spot: Spot) -> str:
    """offshore / cross-shore / onshore relative to the spot (SDD 11)."""
    center, _ = scoring._window_center_and_half(spot.optimal_wind_dir)
    dist = scoring.angular_distance(wind_from, center)
    if dist <= 45:
        return "offshore"
    if dist <= 135:
        return "cross-shore"
    return "onshore"


def build_forecast(spot: Spot) -> dict:
    """Fetch + compute the full per-spot forecast payload."""
    fc = openmeteo.fetch_spot_forecast(spot.lat, spot.lon)

    sea = {t: h for t, h in zip(fc.times, fc.sea_level) if h is not None}
    tide_state = tide_mod.classify_day(sea)

    hours = []
    for i, t in enumerate(fc.times):
        hs = fc.wave_height[i]
        tp = fc.wave_period[i]
        wd = fc.wave_direction[i]
        ws = fc.wind_speed[i]
        wdir = fc.wind_direction[i]
        ts = tide_state.get(t, "mid")

        # confidence from the available spread models this hour
        model_heights = [fc.spread_heights[m][i] for m in fc.spread_heights]
        conf, spread = confidence.confidence_for_hour(model_heights)

        if None in (hs, tp, wd, ws, wdir):
            hours.append({
                "time": t.isoformat(), "score": None, "label": "No data",
                "confidence": conf, "missing": True,
            })
            continue

        r = scoring.score_hour(
            spot, wave_height_m=hs, wave_period_s=tp, wave_from_deg=wd,
            wind_speed_ms=ws, wind_from_deg=wdir, tide_state=ts,
        )
        hours.append({
            "time": t.isoformat(),
            "score": round(r.score, 2),
            "label": r.label,
            "swell": {
                "height_m": round(hs, 2), "period_s": round(tp, 1),
                "direction_deg": round(wd), "direction_compass": compass(wd),
            },
            "wind": {
                "speed_ms": round(ws, 1), "direction_deg": round(wdir),
                "direction_compass": compass(wdir),
                "relation": _wind_relation(wdir, spot),
            },
            "tide": {"state": ts},
            "confidence": conf,
            "spread_m": round(spread, 2) if spread is not None else None,
            "breakdown": r.as_dict()["components"],
            "flat": r.flat,
        })

    return {
        "spot": _spot_meta(spot),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "days": dayparts.build_days(hours),
    }


def _spot_meta(spot: Spot) -> dict:
    return {
        "id": spot.id, "name": spot.name, "display_name": spot.display_name,
        "aka": spot.aka, "county": spot.county, "lat": spot.lat, "lon": spot.lon,
        "break_type": spot.break_type, "skill": spot.skill,
        "tide_pref": spot.tide, "hazards": spot.hazards, "notes": spot.notes,
        "orientation_verified": spot.orientation_verified,
    }


def get_forecast(spot: Spot, *, force: bool = False) -> dict:
    """Cached read with on-open staleness refresh (SDD 5)."""
    if force or cache.is_stale(spot.id):
        payload = build_forecast(spot)
        cache.put(spot.id, payload)
        return payload
    entry = cache.get(spot.id)
    return entry["payload"] if entry else build_and_cache(spot)


def build_and_cache(spot: Spot) -> dict:
    cache.init_db()  # idempotent; safe if called before app startup
    payload = build_forecast(spot)
    cache.put(spot.id, payload)
    return payload


def refresh_all() -> int:
    """Refresh every spot (used by the scheduler). Returns count refreshed.

    Spots are independent, so refresh them concurrently — important on slow
    links where sequential fetches of 10 spots take minutes."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cache.init_db()
    n = 0

    def _one(spot):
        build_and_cache(spot)
        return spot.id

    with ThreadPoolExecutor(max_workers=config.REFRESH_CONCURRENCY) as ex:
        futures = {ex.submit(_one, s): s for s in load_spots()}
        for fut in as_completed(futures):
            spot = futures[fut]
            try:
                fut.result()
                n += 1
            except Exception as e:  # noqa: BLE001
                print(f"[refresh] {spot.id} failed: {e}")
    return n


def build_overview() -> dict:
    """Home-page payload: current rating per spot, grouped by county (SDD 10/11).

    Resilient: a spot that can't be fetched (and has no cache yet) is returned
    with pending=True rather than failing the whole page. The UI shows it as
    still loading; a later refresh fills it in."""
    counties: dict[str, list[dict]] = {}
    for spot in load_spots():
        entry = {
            "id": spot.id, "name": spot.name, "display_name": spot.display_name,
            "break_type": spot.break_type, "skill": spot.skill,
        }
        try:
            fc = get_forecast(spot)
            entry["current"] = _current_hour(fc["hours"])
            days = fc.get("days") or dayparts.build_days(fc["hours"])
            entry["days"] = days[:7]
            entry["pending"] = False
        except Exception as e:  # noqa: BLE001
            # serve stale cache if we have any, else mark pending
            cached = cache.get(spot.id)
            if cached:
                fc = cached["payload"]
                entry["current"] = _current_hour(fc["hours"])
                entry["days"] = (fc.get("days") or [])[:7]
                entry["pending"] = False
                entry["stale"] = True
            else:
                entry["current"] = None
                entry["days"] = []
                entry["pending"] = True
                print(f"[overview] {spot.id} pending: {e}")
        counties.setdefault(spot.county, []).append(entry)

    ordered = []
    for county in config.COUNTY_ORDER:
        if county in counties:
            ordered.append({"county": county, "spots": counties[county]})
    # any counties not in the configured order, appended
    for county, spots in counties.items():
        if county not in config.COUNTY_ORDER:
            ordered.append({"county": county, "spots": spots})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counties": ordered,
    }


def _current_hour(hours: list[dict]) -> dict | None:
    """The hour closest to now (forecasts start at 00:00 today)."""
    now = datetime.now(timezone.utc)
    best = None
    best_dt = None
    for h in hours:
        t = datetime.fromisoformat(h["time"])
        if best is None or abs((t - now).total_seconds()) < abs((best_dt - now).total_seconds()):
            best, best_dt = h, t
    return best


def _today_strip(hours: list[dict], step: int = 2) -> list[dict]:
    """A light sparkline for the home card: score + wave height every `step`
    hours for the first 24h, so the card can draw a swell-height background."""
    strip = []
    for h in hours[:24:step]:
        swell = h.get("swell") or {}
        strip.append({
            "time": h["time"],
            "score": h.get("score"),
            "label": h.get("label"),
            "height_m": swell.get("height_m"),
        })
    return strip


# central-ish west-coast point for the regional weather narrative
_WX_LAT, _WX_LON = 53.4, -9.9


def build_summary() -> dict:
    """Cross-spot surf-weather digest for the home-page Summary (SDD 10/11)."""
    pairs = []
    for spot in load_spots():
        try:
            fc = get_forecast(spot)
        except Exception:  # noqa: BLE001
            cached = cache.get(spot.id)
            if not cached:
                continue
            fc = cached["payload"]
        pairs.append((spot.name, fc))

    weather = None
    try:
        weather = openmeteo.fetch_weather(_WX_LAT, _WX_LON)
    except Exception as e:  # noqa: BLE001
        print(f"[summary] weather fetch failed (narrative degrades): {e}")

    return summary_mod.build_summary(pairs, weather=weather)
