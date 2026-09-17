"""The 0-5 surf rating engine (SDD §6).

Transparent, rules-based scoring per spot per hour. Produces a continuous 0-5
score plus a Surfline-style label and a component breakdown so the UI can explain
*why* a rating is what it is.

Scale (SDD §6):
    0 No surf | 1 Very poor | 2 Poor | 3 Fair | 4 Good | 5 Very good
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .spots import Spot

# Score band -> label. Index by rounded score.
LABELS = {
    0: "No surf",
    1: "Very poor",
    2: "Poor",
    3: "Fair",
    4: "Good",
    5: "Very good",
}


def label_for(score: float) -> str:
    """Band a continuous 0-5 score to its Surfline-style label.

    Uses half-up banding (e.g. 3.5-4.49 -> Good, 4.5+ -> Very good) rather than
    Python's banker's rounding, so boundary values match the SDD §6 bands.
    """
    band = int(math.floor(score + 0.5))
    band = max(0, min(5, band))
    return LABELS[band]


def angular_distance(a: float, b: float) -> float:
    """Smallest distance between two bearings in degrees (handles 0/360 wrap)."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _in_window(bearing: float, window: tuple[float, float]) -> bool:
    """Is a bearing inside an [start, end] window, accounting for wrap?"""
    start, end = window
    if start <= end:
        return start <= bearing <= end
    # wrapped window, e.g. (350, 20)
    return bearing >= start or bearing <= end


def window_center_and_half(window: tuple[float, float]) -> tuple[float, float]:
    start, end = window
    span = (end - start) % 360.0
    half = span / 2.0
    center = (start + half) % 360.0
    return center, half


@dataclass
class ScoreBreakdown:
    """Per-hour rating and the factors that produced it (0-1 unless noted)."""
    score: float                 # final 0-5
    label: str
    base: float                  # size/power contribution, 0-5 pre-factors
    swell_dir_factor: float      # 0-1 multiplier
    wind_factor: float           # 0-1 multiplier
    tide_factor: float           # 0-1 multiplier
    flat: bool                   # True if forced to 0 (below workable swell)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "label": self.label,
            "components": {
                "base": round(self.base, 2),
                "swell_direction": round(self.swell_dir_factor, 2),
                "wind": round(self.wind_factor, 2),
                "tide": round(self.tide_factor, 2),
            },
            "flat": self.flat,
        }


def _base_from_size_period(height_m: float, period_s: float,
                           spot: Spot) -> float:
    """Size & power -> 0-5 base, clamped to the spot's workable range.

    Below the workable minimum returns 0 (caller enforces the hard 'No surf'
    floor). Within range, larger + longer-period swell scores higher; period is
    a quality multiplier because long-period groundswell has far more push than
    short-period windswell of the same height.
    """
    lo, hi = spot.swell_height_m
    if height_m < lo:
        return 0.0

    # Size: linear from lo->hi mapped to ~2.5->5, capped (bigger isn't always
    # better but for these spots we treat in-range-and-up as good size).
    size = 2.5 + 2.5 * min(1.0, (height_m - lo) / max(0.1, (hi - lo)))

    # Period quality: <7s poor windswell, >=12s excellent groundswell.
    if period_s <= 6:
        period_q = 0.6
    elif period_s >= 12:
        period_q = 1.0
    else:
        period_q = 0.6 + 0.4 * (period_s - 6) / 6.0

    return min(5.0, size * period_q)


def _swell_dir_factor(swell_from_deg: float, spot: Spot) -> float:
    """1.0 inside the optimal window, decaying with angular distance outside."""
    if _in_window(swell_from_deg, spot.optimal_swell_dir):
        return 1.0
    _, half = window_center_and_half(spot.optimal_swell_dir)
    # distance from the nearest window edge
    start, end = spot.optimal_swell_dir
    dist = min(angular_distance(swell_from_deg, start),
               angular_distance(swell_from_deg, end))
    # Reefs are pickier about direction than beaches.
    falloff = 40.0 if spot.is_reef else 70.0
    return max(0.0, 1.0 - dist / falloff)


def _wind_factor(wind_from_deg: float, wind_speed_ms: float,
                 spot: Spot) -> float:
    """Offshore = good, onshore = bad, scaled by wind speed.

    Light winds barely matter (clean either way); strong onshore wrecks it.
    optimal_wind_dir is the offshore bearing window (wind coming FROM the land).
    """
    # How offshore is the wind? 1.0 = dead offshore, 0 = dead onshore.
    center, _ = window_center_and_half(spot.optimal_wind_dir)
    off_dist = angular_distance(wind_from_deg, center)  # 0..180
    offshoreness = 1.0 - off_dist / 180.0               # 1 offshore .. 0 onshore

    # Weight by speed: below ~3 m/s wind hardly matters; above ~12 m/s it
    # dominates. Blend between "neutral" and the offshoreness signal.
    if wind_speed_ms <= 3:
        speed_w = 0.15
    elif wind_speed_ms >= 12:
        speed_w = 1.0
    else:
        speed_w = 0.15 + 0.85 * (wind_speed_ms - 3) / 9.0

    # Neutral-good (0.9) when calm — light wind is clean; pull toward the
    # offshoreness signal as wind strengthens (strong onshore tanks it).
    return (1.0 - speed_w) * 0.9 + speed_w * offshoreness


def _tide_factor(tide_state: str, spot: Spot) -> float:
    """Match classified tide state (low/mid/high) to the spot preference."""
    pref = spot.tide
    if pref == "any" or not pref:
        return 1.0
    # Range like "low-mid" -> {low, mid}
    if "-" in pref:
        a, b = pref.split("-", 1)
        order = ["low", "mid", "high"]
        try:
            allowed = set(order[order.index(a):order.index(b) + 1])
        except ValueError:
            allowed = {a, b}
    else:
        allowed = {pref}

    if tide_state in allowed:
        return 1.0
    # Partial credit for adjacent state (mid is adjacent to both low and high).
    adjacency = {
        ("low", "mid"), ("mid", "low"),
        ("mid", "high"), ("high", "mid"),
    }
    if any((tide_state, p) in adjacency for p in allowed):
        return 0.7
    return 0.45  # wrong tide (e.g. wanted low, got high) — reef penalised more


def score_hour(
    spot: Spot,
    *,
    wave_height_m: float,
    wave_period_s: float,
    wave_from_deg: float,
    wind_speed_ms: float,
    wind_from_deg: float,
    tide_state: str,
) -> ScoreBreakdown:
    """Score a single hour for a spot. Returns the 0-5 rating + breakdown."""
    base = _base_from_size_period(wave_height_m, wave_period_s, spot)

    # Hard 'No surf' floor: below workable swell there is no surf regardless of
    # perfect wind/tide (SDD §6).
    if base <= 0.0:
        return ScoreBreakdown(0.0, LABELS[0], 0.0, 0.0, 0.0, 0.0, flat=True)

    swell_dir_factor = _swell_dir_factor(wave_from_deg, spot)
    wind_factor = _wind_factor(wind_from_deg, wind_speed_ms, spot)
    tide_factor = _tide_factor(tide_state, spot)

    score = base * swell_dir_factor * wind_factor * tide_factor
    score = max(0.0, min(5.0, score))

    return ScoreBreakdown(
        score=score,
        label=label_for(score),
        base=base,
        swell_dir_factor=swell_dir_factor,
        wind_factor=wind_factor,
        tide_factor=tide_factor,
        flat=False,
    )
