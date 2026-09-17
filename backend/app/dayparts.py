"""Group scored hours into days -> dayparts (morning/afternoon/evening).

Surfline-style: each day is summarised as three bars. Used by both the home
overview (7 days) and the spot detail strip (full horizon), so the two views
share one data shape and render identically.

Note: dayparts are bucketed by UTC hour (data is GMT). In Irish summer this is
~1h off local; acceptable for v1, could be localised later.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime

# (label, start_hour_inclusive, end_hour_exclusive)
PART_DEFS = [("morning", 6, 12), ("afternoon", 12, 18), ("evening", 18, 24)]


def _circular_mean(degs: list[float | None]) -> float | None:
    vals = [d for d in degs if d is not None]
    if not vals:
        return None
    xs = sum(math.cos(math.radians(d)) for d in vals)
    ys = sum(math.sin(math.radians(d)) for d in vals)
    if abs(xs) < 1e-9 and abs(ys) < 1e-9:
        return None
    return round(math.degrees(math.atan2(ys, xs)) % 360)


def _avg(xs: list[float | None], ndigits: int = 2) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), ndigits) if vals else None


def _part_summary(name: str, phours: list[dict]) -> dict:
    if not phours:
        return {"part": name, "score": None, "height_m": None}
    swell = [h.get("swell") or {} for h in phours]
    wind = [h.get("wind") or {} for h in phours]
    mid = phours[len(phours) // 2]
    return {
        "part": name,
        "score": _avg([h.get("score") for h in phours]),
        "height_m": _avg([s.get("height_m") for s in swell]),
        "period_s": _avg([s.get("period_s") for s in swell], 1),
        "swell_dir": _circular_mean([s.get("direction_deg") for s in swell]),
        "wind_speed": _avg([w.get("speed_ms") for w in wind], 1),
        "wind_dir": _circular_mean([w.get("direction_deg") for w in wind]),
        "confidence": mid.get("confidence"),
    }


def build_days(hours: list[dict]) -> list[dict]:
    """Return a list of days, each with three daypart summaries."""
    by_date: OrderedDict[str, list[dict]] = OrderedDict()
    for h in hours:
        by_date.setdefault(h["time"][:10], []).append(h)

    days = []
    for date, dhours in by_date.items():
        good = [h for h in dhours if not h.get("missing")]
        parts = []
        for name, start, end in PART_DEFS:
            phours = [
                h for h in good
                if start <= datetime.fromisoformat(h["time"]).hour < end
            ]
            parts.append(_part_summary(name, phours))
        heights = [
            (h.get("swell") or {}).get("height_m")
            for h in good if (h.get("swell") or {}).get("height_m") is not None
        ]
        days.append({
            "date": date,
            "parts": parts,
            "height_min": round(min(heights), 1) if heights else None,
            "height_max": round(max(heights), 1) if heights else None,
        })
    return days
