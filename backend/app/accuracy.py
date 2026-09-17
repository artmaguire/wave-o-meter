"""Model-accuracy scorecard (SDD §13): how well each forecast model has matched
MEASURED buoy conditions over the recent past.

For each offshore buoy we pull the last N days of measured significant wave
height and the same-window forecast from each model, then compute MAE + Pearson
correlation. This is the legitimate "which model to trust" signal — the same
method as the feasibility spike, run on a rolling window and cached daily.
"""

from __future__ import annotations

import csv
import io
import math
import statistics
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import config, openmeteo

ERDDAP_CSV = "https://erddap.marine.ie/erddap/tabledap/IWBNetwork.csv"

# Offshore buoys with open-ocean exposure + their coordinates (from the spike).
VALIDATION_BUOYS = [
    ("M6", 53.07, -15.88, "Deep Atlantic"),
    ("M3", 51.22, -10.55, "SW approaches"),
]

WINDOW_DAYS = 14
_cache: dict | None = None
_cache_ts: float = 0.0
_TTL_S = 24 * 3600  # recompute daily


def _measured(station: str, start: str, end: str) -> dict[datetime, float]:
    q = [
        "time,WaveHeight",
        f'station_id="{station}"',
        f"time>={start}T00:00:00Z",
        f"time<={end}T23:59:59Z",
    ]
    url = f"{ERDDAP_CSV}?" + "&".join(urllib.parse.quote(c, safe=",") for c in q)
    raw = openmeteo._get_client().get(url).text
    rows = list(csv.reader(io.StringIO(raw)))
    out: dict[datetime, list[float]] = {}
    for r in rows[2:]:  # skip name + unit rows
        if len(r) < 2 or not r[1]:
            continue
        try:
            t = datetime.fromisoformat(r[0].replace("Z", "+00:00"))
            v = float(r[1])
        except ValueError:
            continue
        if 0 <= v <= 30:
            out.setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(v)
    return {h: statistics.mean(v) for h, v in out.items()}


def _forecast_series(lat, lon, model, start, end) -> dict[datetime, float]:
    params = {
        "latitude": lat, "longitude": lon, "hourly": "wave_height",
        "models": model, "start_date": start, "end_date": end, "timezone": "GMT",
    }
    url = f"{config.MARINE_API}?{urllib.parse.urlencode(params)}"
    payload = openmeteo._get(url)
    h = payload.get("hourly", {})
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
             for t in h.get("time", [])]
    vals = h.get(f"wave_height_{model}") or h.get("wave_height") or []
    return {t: float(v) for t, v in zip(times, vals) if v is not None}


def _stats(pred: dict, obs: dict):
    pairs = [(pred[k], obs[k]) for k in pred.keys() & obs.keys()]
    if len(pairs) < 6:
        return None
    diffs = [p - o for p, o in pairs]
    mae = statistics.mean(abs(d) for d in diffs)
    ps = [p for p, _ in pairs]
    os_ = [o for _, o in pairs]
    mp, mo = statistics.mean(ps), statistics.mean(os_)
    num = sum((p - mp) * (o - mo) for p, o in pairs)
    da = math.sqrt(sum((p - mp) ** 2 for p in ps))
    db = math.sqrt(sum((o - mo) ** 2 for o in os_))
    corr = num / (da * db) if da and db else None
    return {"n": len(pairs), "mae": round(mae, 2),
            "corr": round(corr, 2) if corr is not None else None}


def build_scorecard(force: bool = False) -> dict:
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache is not None and (now - _cache_ts) < _TTL_S:
        return _cache

    end = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    start = end - timedelta(days=WINDOW_DAYS)
    s, e = start.isoformat(), end.isoformat()

    results = []
    for station, lat, lon, label in VALIDATION_BUOYS:
        try:
            obs = _measured(station, s, e)
        except Exception:  # noqa: BLE001
            continue
        if not obs:
            continue
        models = []
        for model in [config.PRIMARY_WAVE_MODEL, *config.SPREAD_WAVE_MODELS]:
            try:
                pred = _forecast_series(lat, lon, model, s, e)
            except Exception:  # noqa: BLE001
                continue
            st = _stats(pred, obs)
            if st:
                models.append({"model": model, **st})
        if models:
            models.sort(key=lambda m: m["mae"])
            results.append({
                "buoy": station, "label": label,
                "window_days": WINDOW_DAYS, "models": models,
                "best": models[0]["model"],
            })

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": f"{s} to {e}",
        "buoys": results,
    }
    _cache, _cache_ts = out, now
    return out
