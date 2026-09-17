"""Tide classification (SDD 6).

Open-Meteo gives `sea_level_height_msl` as a continuous curve. We classify each
hour into low / mid / high by its position within that day's local min-max range.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime


def classify_day(heights_by_hour: dict[datetime, float]) -> dict[datetime, str]:
    """Classify each hour's tide as low/mid/high within its own calendar day.

    Bottom third of the day's range -> low, middle -> mid, top -> high.
    Using per-day min/max keeps the classification robust to the spring/neap
    cycle (absolute heights drift, but 'low for today' stays meaningful).
    """
    by_day: dict[str, dict[datetime, float]] = defaultdict(dict)
    for t, h in heights_by_hour.items():
        by_day[t.date().isoformat()][t] = h

    out: dict[datetime, str] = {}
    for day_hours in by_day.values():
        vals = [v for v in day_hours.values() if v is not None]
        if not vals:
            for t in day_hours:
                out[t] = "mid"
            continue
        lo, hi = min(vals), max(vals)
        span = hi - lo
        for t, h in day_hours.items():
            if h is None or span < 1e-6:
                out[t] = "mid"
                continue
            frac = (h - lo) / span
            if frac < 1 / 3:
                out[t] = "low"
            elif frac < 2 / 3:
                out[t] = "mid"
            else:
                out[t] = "high"
    return out
