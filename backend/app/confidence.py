"""Confidence indicator from model spread (SDD 8).

Confidence quality depends on how many wave models cover a given hour:
  Days 1-3  : ECMWF + meteofrance_wave + EWAM -> full three-model spread
  Days 4-10 : ECMWF + meteofrance_wave        -> two-model spread
  Days 11-12: ECMWF only                      -> no spread; long-range outlook

IMPORTANT (learned during implementation): unlike the deep-ocean buoys in the
spike (models agree to ~0.2 m), NEARSHORE the models genuinely disagree by ~1.6 m
on average because each downscales to the coast differently. Absolute spread is
therefore a poor signal inshore. We use RELATIVE spread (spread / mean height):
a 1 m disagreement on a 4 m swell is far more trustworthy than 1 m on a 1.5 m
swell. Thresholds below are set from the observed distribution across all 10
spots (relative-spread median ~0.69, p33 ~0.48, p66 ~0.79).
"""

from __future__ import annotations

import statistics

# Relative-spread thresholds (spread / mean), when >=2 models are available.
_HIGH_MAX = 0.48   # models relatively tight -> high confidence
_MED_MAX = 0.79    # moderate divergence
_MIN_MEAN = 0.3    # below this, heights are tiny; relative spread is unstable

LONG_RANGE = "long_range"   # only ECMWF available (days 11-12)
HIGH = "high"
MEDIUM = "medium"
LOW = "low"


def confidence_for_hour(model_heights: list[float]) -> tuple[str, float | None]:
    """Return (confidence_level, absolute_spread_m).

    model_heights: available model wave heights for this hour (may contain None).
    With <2 non-null models there is no spread to measure -> long-range outlook.
    The returned spread is absolute metres (for display); the level is decided on
    relative spread.
    """
    vals = [h for h in model_heights if h is not None]
    if len(vals) < 2:
        return LONG_RANGE, None

    spread = max(vals) - min(vals)
    mean = statistics.mean(vals)

    # Tiny seas: everyone's near zero, relative spread is noisy. If the sea is
    # small in absolute terms too, call it high confidence (agreement on "small").
    if mean < _MIN_MEAN:
        return (HIGH if spread < 0.3 else MEDIUM), spread

    rel = spread / mean
    if rel <= _HIGH_MAX:
        return HIGH, spread
    if rel <= _MED_MAX:
        return MEDIUM, spread
    return LOW, spread
