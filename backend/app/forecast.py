"""Forecast orchestration (SDD 5, 6, 8, 10).

Ties the pieces together: fetch raw data -> classify tide -> score each hour ->
compute confidence -> build the JSON payloads the API serves, and cache them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import cache, confidence, config, dayparts, openmeteo, scoring
from . import summary as summary_mod
from . import tide as tide_mod
from .spots import Spot, load_spots

log = logging.getLogger("waveometer.forecast")

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg: float | None) -> str | None:
    if deg is None:
        return None
    return _COMPASS[round(deg / 22.5) % 16]


def _rnd(v, ndigits=2):
    return round(v, ndigits) if v is not None else None


def wetsuit_for(sst: float | None) -> str | None:
    """Wetsuit guidance for Irish water temps (°C).

    Calibrated to the Irish reality rather than generic tables: a 4/3 is the
    year-round workhorse here. The spot guides agree — 7 of 9 call for a 4/3
    through the 14-17 °C "summer" (Jun-Oct), stepping up to 5/4 hooded with
    boots and gloves at 9-12 °C in winter. A 3/2 is only ever borderline on the
    warmest days, so it's never the default.
    """
    if sst is None:
        return None
    if sst >= 14:
        return "4/3 mm"
    if sst >= 12:
        return "4/3 or 5/4 mm"
    if sst >= 10:
        return "5/4 mm hooded"
    return "5/4/3 mm hooded"


def _weather_desc(code: int | None) -> str | None:
    """WMO weather code -> short label + emoji."""
    if code is None:
        return None
    m = {
        0: "☀ Clear", 1: "🌤 Mostly clear", 2: "⛅ Partly cloudy", 3: "☁ Overcast",
        45: "🌫 Fog", 48: "🌫 Fog",
        51: "🌦 Light drizzle", 53: "🌦 Drizzle", 55: "🌧 Heavy drizzle",
        61: "🌧 Light rain", 63: "🌧 Rain", 65: "🌧 Heavy rain",
        66: "🌧 Freezing rain", 67: "🌧 Freezing rain",
        71: "🌨 Light snow", 73: "🌨 Snow", 75: "❄ Heavy snow",
        80: "🌦 Showers", 81: "🌧 Showers", 82: "⛈ Heavy showers",
        95: "⛈ Thunderstorm", 96: "⛈ Thunderstorm", 99: "⛈ Thunderstorm",
    }
    return m.get(int(code), None)


def wave_power_kw_m(height_m: float | None, period_s: float | None) -> float | None:
    """Deep-water wave power per metre of crest, in kW/m.

    P = (rho * g^2 / 64pi) * H^2 * T  ~= 0.49 * H^2 * T  (kW/m, H in m, T in s)
    Power scales with the SQUARE of height and linearly with period, which is
    why a long-period swell hits far harder than a short-period one of the same
    size — the number surfers feel as "punch".
    """
    if height_m is None or period_s is None:
        return None
    return round(0.49 * (height_m ** 2) * period_s, 1)


# Power bands (kW/m) -> label. Tuned for Irish beach/reef surf: ~10 is a soft
# small day, ~30 is solid and punchy, 60+ is heavy.
_POWER_BANDS = [
    (8, "gentle"),
    (20, "moderate"),
    (40, "punchy"),
    (70, "powerful"),
]


def power_label(kw_m: float | None) -> str | None:
    if kw_m is None:
        return None
    for limit, label in _POWER_BANDS:
        if kw_m < limit:
            return label
    return "heavy"


def _wave_components(fc, i) -> dict:
    """Groundswell vs wind-wave split — the key surf-quality signal.
    Clean long-period groundswell surfs far better than messy wind chop of the
    same height."""
    sh = fc.swell_height[i]
    wh = fc.wind_wave_height[i]
    dominant = "swell"
    if sh is not None and wh is not None:
        dominant = "swell" if sh >= wh else "windsea"
    return {
        "swell_height_m": _rnd(sh),
        "swell_period_s": _rnd(fc.swell_period[i], 1),
        "swell_dir_deg": _rnd(fc.swell_direction[i], 0),
        "swell_dir_compass": compass(fc.swell_direction[i]),
        "wind_wave_height_m": _rnd(wh),
        "dominant": dominant,
        "secondary": _secondary_swell(fc, i),
    }


def _secondary_swell(fc, i) -> dict | None:
    """A meaningful secondary swell train (a second swell from another
    direction), if present (>=0.4 m)."""
    h = fc.sec_swell_height[i]
    if h is None or h < 0.4:
        return None
    return {
        "height_m": _rnd(h),
        "period_s": _rnd(fc.sec_swell_period[i], 1),
        "dir_deg": _rnd(fc.sec_swell_direction[i], 0),
        "dir_compass": compass(fc.sec_swell_direction[i]),
    }


def _wind_relation(wind_from: float, spot: Spot) -> str:
    """offshore / cross-shore / onshore relative to the spot (SDD 11)."""
    center, _ = scoring.window_center_and_half(spot.optimal_wind_dir)
    dist = scoring.angular_distance(wind_from, center)
    if dist <= 45:
        return "offshore"
    if dist <= 135:
        return "cross-shore"
    return "onshore"


def build_forecast(spot: Spot) -> dict:
    """Fetch + compute the full per-spot forecast payload."""
    fc = openmeteo.fetch_spot_forecast(spot.lat, spot.lon)

    sea = {t: h for t, h in zip(fc.times, fc.sea_level, strict=False) if h is not None}
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
            gust_ms=fc.wind_gust[i],
            swell_height_m=fc.swell_height[i],
            wind_wave_height_m=fc.wind_wave_height[i],
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
                "speed_ms": round(ws, 1),
                "gust_ms": _rnd(fc.wind_gust[i], 1),
                "direction_deg": round(wdir),
                "direction_compass": compass(wdir),
                "relation": _wind_relation(wdir, spot),
            },
            "components": _wave_components(fc, i),
            "power_kw_m": wave_power_kw_m(hs, tp),
            "power_label": power_label(wave_power_kw_m(hs, tp)),
            "sea_temp_c": _rnd(fc.sea_temp[i], 1),
            "tide": {"state": ts},
            "confidence": conf,
            "spread_m": round(spread, 2) if spread is not None else None,
            "breakdown": r.as_dict()["components"],
            "flat": r.flat,
        })

    days = dayparts.build_days(hours)
    # enrich each day with sun times + weather + a representative sea temp/wetsuit
    for d in days:
        dinfo = fc.daily.get(d["date"], {})
        d["sunrise"] = dinfo.get("sunrise")
        d["sunset"] = dinfo.get("sunset")
        d["weather"] = _weather_desc(dinfo.get("weather_code"))
        d["uv"] = dinfo.get("uv")
        d["air_temp_c"] = dinfo.get("air_max")
        # sea temp: pick a midday hour on that date
        day_hours = [h for h in hours
                     if h["time"][:10] == d["date"] and not h.get("missing")]
        sst = None
        if day_hours:
            sst = day_hours[len(day_hours) // 2].get("sea_temp_c")
        d["sea_temp_c"] = sst
        d["wetsuit"] = wetsuit_for(sst)

    return {
        "spot": spot_meta(spot),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "days": days,
    }


def spot_meta(spot: Spot) -> dict:
    return {
        "id": spot.id, "name": spot.name, "display_name": spot.display_name,
        "aka": spot.aka, "county": spot.county, "lat": spot.lat, "lon": spot.lon,
        "break_type": spot.break_type, "skill": spot.skill,
        "tide_pref": spot.tide, "hazards": spot.hazards, "notes": spot.notes,
        "orientation_verified": spot.orientation_verified,
        "links": spot.links,
        "profile": _spot_profile(spot),
    }


def _spot_profile(spot: Spot) -> dict:
    """Full conditions card for the beach-breakdown UI, combining the stored
    profile with the compass ranges derived from the scoring windows."""
    def rng(w):
        return f"{compass(w[0])}-{compass(w[1])}"
    return {
        **spot.profile,
        "break_type": spot.break_type,
        "skill": spot.skill,
        "swell_dir": rng(spot.optimal_swell_dir),
        "wind_dir": rng(spot.optimal_wind_dir),
        "tide_position": spot.tide,
        "size_ft": f"{round(spot.swell_height_m[0]*3.281*0.6)}"
                   f"-{round(spot.swell_height_m[1]*3.281*0.6)} ft",
    }


def get_forecast(spot: Spot, *, force: bool = False) -> dict:
    """Cached read with on-open staleness refresh (SDD 5).

    Reads the cache entry ONCE and checks staleness from its timestamp, so a
    warm read is a single DB connect + single JSON parse (not two of each)."""
    if not force:
        entry = cache.get(spot.id)
        if entry and not cache.is_stale_ts(entry["fetched_at"]):
            return entry["payload"]
    return build_and_cache(spot)


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
                log.warning("refresh %s failed: %s", spot.id, e)
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
            entry["trend"] = _rating_trend(days)
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
                log.warning("overview %s pending: %s", spot.id, e)
        counties.setdefault(spot.county, []).append(entry)

    ordered = []
    for county in config.COUNTY_ORDER:
        if county in counties:
            ordered.append({"county": county, "spots": counties[county]})
    # any counties not in the configured order, appended
    for county, spots in counties.items():
        if county not in config.COUNTY_ORDER:
            ordered.append({"county": county, "spots": spots})

    # best spot right now (across all), for the home-page headline
    best_now = None
    for c in ordered:
        for sp in c["spots"]:
            cur = sp.get("current") or {}
            sc = cur.get("score")
            if sc is None:
                continue
            if best_now is None or sc > best_now["score"]:
                best_now = {"id": sp["id"], "name": sp["name"],
                            "score": sc, "label": cur.get("label")}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counties": ordered,
        "best_now": best_now,
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


def _rating_trend(days: list[dict]) -> str:
    """improving / steady / dropping across the next few DAYS.

    The arrow sits next to the 7-day calendar, so it should describe where the
    week is heading — today's best vs the best of the next 2-3 days — not the
    next few hours (which felt wrong when a flat morning preceded a building
    week).
    """
    def day_best(d):
        return max((p.get("score") or 0) for p in d.get("parts", [])) if d.get("parts") else 0

    week = days[:5]
    if len(week) < 2:
        return "steady"
    today = day_best(week[0])
    ahead = [day_best(d) for d in week[1:4]]
    if max(ahead) - today >= 0.6:
        return "improving"
    if today - max(ahead) >= 0.6:      # even the best day ahead is well below today
        return "dropping"
    return "steady"


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
        log.warning("summary weather fetch failed (narrative degrades): %s", e)

    return summary_mod.build_summary(pairs, weather=weather)
