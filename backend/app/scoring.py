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
    wind_factor: float           # 0-1 multiplier (incl. gust penalty)
    tide_factor: float           # 0-1 multiplier
    clean_factor: float          # 0-1 multiplier (groundswell vs windsea)
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
                "clean": round(self.clean_factor, 2),
            },
            "flat": self.flat,
        }


def _period_quality(period_s: float, spot: Spot) -> float:
    """Swell-period quality, stricter for reefs.

    Long-period groundswell has far more push and cleaner form. Reefs (Easkey,
    Magharees) barely work on short-period windswell, so they need longer
    period to score well; beach breaks are more forgiving.
    """
    if spot.is_reef:
        # reef: wants groundswell — modest below ~8s, excellent >=12s
        lo_s, hi_s, floor = 8.0, 12.0, 0.55
    else:
        # beach: more forgiving — modest below ~6s, excellent >=11s
        lo_s, hi_s, floor = 6.0, 11.0, 0.65
    if period_s <= lo_s:
        return floor
    if period_s >= hi_s:
        return 1.0
    return floor + (1.0 - floor) * (period_s - lo_s) / (hi_s - lo_s)


# Size-curve shape. MARGINAL_BAND is the fraction of the workable minimum over
# which surf ramps in (no hard cliff at the exact minimum); OVERSIZE_FACTOR is
# how far above the workable max a spot becomes effectively unsurfable.
MARGINAL_BAND = 0.35
OVERSIZE_FACTOR = 2.0


def _size_quality(height_m: float, spot: Spot) -> float:
    """0-1 size quality for a spot's workable range.

    Shape: ramps in gently from just under the workable minimum (real surf
    doesn't switch on at an exact centimetre), rises to full quality by the top
    of the range, then decays toward zero as it oversizes and starts closing out.
    """
    lo, hi = spot.swell_height_m

    # Below the range: a marginal band that ramps 0 -> 0.55 rather than a cliff.
    marginal_from = lo * (1.0 - MARGINAL_BAND)
    if height_m <= marginal_from:
        return 0.0
    if height_m < lo:
        frac = (height_m - marginal_from) / max(0.05, lo - marginal_from)
        return 0.7 * frac          # meets the in-range curve at exactly 0.7

    # In range: 0.7 at the minimum rising to 1.0 partway up.
    if height_m <= hi:
        frac = (height_m - lo) / max(0.1, (hi - lo))
        return min(1.0, 0.7 + 0.5 * frac)

    # Oversized: decay smoothly to ~0 by OVERSIZE_FACTOR x the max, so a genuinely
    # unsurfable day scores like one instead of plateauing.
    unsurfable_at = hi * OVERSIZE_FACTOR
    if height_m >= unsurfable_at:
        return 0.0
    frac = (height_m - hi) / max(0.1, unsurfable_at - hi)
    return max(0.0, 1.0 - frac) ** 1.5


def _base_from_size_period(height_m: float, period_s: float,
                           spot: Spot) -> float:
    """Size & power -> 0-5 base.

    Combines the size-quality curve (which handles the marginal band below the
    workable minimum and the oversize decay above the max) with a
    per-break-type period-quality multiplier. Returns 0 only when the size
    curve itself says there's nothing to surf — the caller turns that into the
    hard "No surf" result.
    """
    size_q = _size_quality(height_m, spot)
    if size_q <= 0.0:
        return 0.0
    period_q = _period_quality(period_s, spot)
    base = 5.0 * size_q * period_q
    # A 5 ("Very good") should be rare — reserved for genuinely standout,
    # long-period groundswell. Cap the base below the very top unless the
    # period is truly long, so a merely-good 10-11s swell tops out around Good.
    if period_s < 12:
        base = min(base, 4.2)
    elif period_s < 14:
        base = min(base, 4.7)
    return min(5.0, base)


def _clean_factor(swell_h: float | None, windwave_h: float | None) -> float:
    """Groundswell vs wind-sea cleanliness (0-1).

    The forecast splits total sea into ground swell and locally-generated wind
    waves. A sea dominated by wind chop is messier and surfs worse than clean
    groundswell of the same total height. Ratio of swell to total drives this.
    """
    if swell_h is None or windwave_h is None:
        return 1.0  # no data -> don't penalise
    total = swell_h + windwave_h
    if total <= 0.05:
        return 1.0
    swell_frac = swell_h / total
    # all groundswell -> 1.0; half wind-sea -> ~0.7; all wind-sea -> ~0.45
    return 0.45 + 0.55 * swell_frac


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
                 spot: Spot, gust_ms: float | None = None) -> float:
    """Offshore = good, onshore = bad, scaled by wind speed, minus a gust penalty.

    Light winds barely matter (clean either way); strong onshore wrecks it.
    Gusty wind (big gap between mean and gust) is bumpy even when offshore, so a
    large gust spread trims the score. optimal_wind_dir is the offshore bearing
    window (wind coming FROM the land); any direction inside it counts as fully
    offshore, decaying only outside — see the direction-quality block.
    """
    # Direction quality respects the spot's offshore WINDOW (consistent with
    # _swell_dir_factor): any wind inside the offshore window is fully offshore
    # (1.0); outside it, quality decays with distance from the nearest edge.
    # Cosine over ~135° of decay keeps side-shore workable and only true onshore
    # (opposite the window) bottoms out. This fixes wide windows, where a genuine
    # offshore direction far from the window CENTRE was previously penalised.
    if _in_window(wind_from_deg, spot.optimal_wind_dir):
        dir_q = 1.0
    else:
        start, end = spot.optimal_wind_dir
        edge_dist = min(angular_distance(wind_from_deg, start),
                        angular_distance(wind_from_deg, end))
        # 0° past the edge -> 1.0, 135°+ past -> ~0.15
        t = min(1.0, edge_dist / 135.0)
        dir_q = 0.15 + 0.85 * (0.5 * (1 + math.cos(math.radians(t * 180.0))))

    # Wind strength gate: light wind barely matters (clean either way); the
    # direction penalty only really bites as wind strengthens.
    #   <=5 m/s  : glassy/light — direction almost irrelevant (factor ~0.9-1.0)
    #   >=14 m/s : strong — direction dominates (onshore ruins it)
    if wind_speed_ms <= 6:
        strength = 0.1
    elif wind_speed_ms >= 15:
        strength = 1.0
    else:
        strength = 0.1 + 0.9 * (wind_speed_ms - 6) / 9.0

    # Blend: calm is ideal (1.0); as wind builds, pull toward dir_q.
    base = (1.0 - strength) * 1.0 + strength * dir_q

    # Very strong wind is unpleasant even offshore (spray, hard to paddle).
    if wind_speed_ms >= 16:
        base *= 0.85

    # Gust penalty: gust spread beyond ~6 m/s over the mean = bumpy.
    if gust_ms is not None and gust_ms > wind_speed_ms:
        spread = gust_ms - wind_speed_ms
        gust_pen = min(0.15, max(0.0, (spread - 6.0) / 10.0 * 0.15))
        base *= (1.0 - gust_pen)

    return max(0.0, min(1.0, base))


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
    gust_ms: float | None = None,
    swell_height_m: float | None = None,
    wind_wave_height_m: float | None = None,
) -> ScoreBreakdown:
    """Score a single hour for a spot. Returns the 0-5 rating + breakdown.

    Optional inputs enrich the score when available:
      gust_ms            -> gust penalty on the wind factor
      swell/wind_wave_h  -> cleanliness factor (groundswell vs wind-sea)
    """
    base = _base_from_size_period(wave_height_m, wave_period_s, spot)

    # Hard 'No surf' floor: below workable swell there is no surf regardless of
    # perfect wind/tide (SDD §6).
    if base <= 0.0:
        return ScoreBreakdown(0.0, LABELS[0], 0.0, 0.0, 0.0, 0.0, 0.0, flat=True)

    swell_dir_factor = _swell_dir_factor(wave_from_deg, spot)
    wind_factor = _wind_factor(wind_from_deg, wind_speed_ms, spot, gust_ms)
    tide_factor = _tide_factor(tide_state, spot)
    clean_factor = _clean_factor(swell_height_m, wind_wave_height_m)

    score = base * swell_dir_factor * wind_factor * tide_factor * clean_factor
    score = max(0.0, min(5.0, score))

    return ScoreBreakdown(
        score=score,
        label=label_for(score),
        base=base,
        swell_dir_factor=swell_dir_factor,
        wind_factor=wind_factor,
        tide_factor=tide_factor,
        clean_factor=clean_factor,
        flat=False,
    )
