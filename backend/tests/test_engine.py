"""Unit tests for the pure forecast-engine helpers:
confidence, tide classification, daypart aggregation, and summary building.
These are deterministic and don't touch the network.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import confidence, dayparts, summary, tide  # noqa: E402

# --- confidence ---

def test_confidence_long_range_when_single_model():
    level, spread = confidence.confidence_for_hour([2.0])
    assert level == confidence.LONG_RANGE and spread is None


def test_confidence_high_when_models_agree():
    # relative spread small -> high
    level, spread = confidence.confidence_for_hour([2.0, 2.1, 2.05])
    assert level == confidence.HIGH
    assert round(spread, 2) == 0.10


def test_confidence_low_when_models_diverge():
    # big relative spread -> low
    level, _ = confidence.confidence_for_hour([1.0, 3.0])
    assert level == confidence.LOW


def test_confidence_tiny_seas_treated_as_agreement():
    # near-flat: small absolute spread -> high despite noisy ratio
    level, _ = confidence.confidence_for_hour([0.1, 0.2])
    assert level in (confidence.HIGH, confidence.MEDIUM)


def test_confidence_ignores_nones():
    level, _ = confidence.confidence_for_hour([2.0, None, 2.1])
    assert level == confidence.HIGH


# --- tide classification ---

def _hours(vals, day="2026-09-20"):
    out = {}
    for i, v in enumerate(vals):
        t = datetime.fromisoformat(f"{day}T{i:02d}:00:00+00:00")
        out[t] = v
    return out


def test_tide_low_mid_high_banding():
    # a rising then falling curve over 12 hours
    vals = [-2, -1.5, -1, 0, 1, 2, 2, 1, 0, -1, -1.5, -2]
    states = tide.classify_day(_hours(vals))
    labels = [states[t] for t in sorted(states)]
    assert "low" in labels and "mid" in labels and "high" in labels
    # the peak hours should be classified high
    assert labels[5] == "high" and labels[6] == "high"
    assert labels[0] == "low"


def test_tide_flat_span_defaults_mid():
    vals = [1.0] * 6  # zero range
    states = tide.classify_day(_hours(vals))
    assert all(v == "mid" for v in states.values())


def test_tide_all_none_defaults_mid():
    hours = {datetime.fromisoformat(f"2026-09-20T{i:02d}:00:00+00:00"): None
             for i in range(4)}
    states = tide.classify_day(hours)
    assert all(v == "mid" for v in states.values())


# --- dayparts ---

def _hour(t, score, h=1.5, wdir=270):
    return {
        "time": t, "score": score,
        "swell": {"height_m": h, "period_s": 10.0, "direction_deg": 280},
        "wind": {"speed_ms": 5.0, "direction_deg": wdir},
    }


def test_dayparts_three_parts_per_day():
    hours = [_hour(f"2026-09-20T{i:02d}:00", 3.0) for i in range(24)]
    days = dayparts.build_days(hours)
    assert len(days) == 1
    assert [p["part"] for p in days[0]["parts"]] == ["morning", "afternoon", "evening"]


def test_dayparts_score_reflects_uniform_window():
    # morning hours 6-11 all score 4 -> the part scores 4
    hours = []
    for i in range(24):
        hours.append(_hour(f"2026-09-20T{i:02d}:00", 4.0 if 6 <= i < 12 else 2.0))
    days = dayparts.build_days(hours)
    morning = next(p for p in days[0]["parts"] if p["part"] == "morning")
    assert morning["score"] == 4.0


def test_dayparts_good_window_not_diluted_by_bad_hours():
    """The real bug: a genuinely good run inside a daypart must not be averaged
    away by later unsurfable hours (e.g. the tide dropping out)."""
    # afternoon (12-17): 3.8 3.7 3.7 3.6 then 2.5 1.6
    scores = {12: 3.8, 13: 3.7, 14: 3.7, 15: 3.6, 16: 2.5, 17: 1.6}
    hours = [_hour(f"2026-09-20T{i:02d}:00", scores.get(i, 1.0)) for i in range(24)]
    part = next(p for p in dayparts.build_days(hours)[0]["parts"]
                if p["part"] == "afternoon")
    assert part["score"] >= 3.5, "good window should survive the later drop-off"
    assert part["score_avg"] < part["score"], "mean is lower than sustained best"


def test_dayparts_single_fluke_hour_does_not_inflate():
    # one standout hour amid poor ones must not make the part look good
    scores = {13: 5.0}
    hours = [_hour(f"2026-09-20T{i:02d}:00", scores.get(i, 1.0)) for i in range(24)]
    part = next(p for p in dayparts.build_days(hours)[0]["parts"]
                if p["part"] == "afternoon")
    assert part["score"] < 3.5


def test_dayparts_height_min_max():
    hours = [_hour(f"2026-09-20T{i:02d}:00", 3.0, h=1.0 + i * 0.1) for i in range(24)]
    d = dayparts.build_days(hours)[0]
    assert d["height_min"] is not None and d["height_max"] >= d["height_min"]


def test_circular_mean_wraps():
    # directions either side of north average to ~north, not ~180
    m = dayparts._circular_mean([350, 10])
    assert m is not None and (m < 20 or m > 340)


# --- summary ---

def _fc_days(scores_by_day):
    """Build a minimal forecast payload with given daypart scores."""
    days = []
    hours = []
    for date, parts in scores_by_day.items():
        dparts = []
        for name, sc in zip(("morning", "afternoon", "evening"), parts, strict=False):
            dparts.append({"part": name, "score": sc, "height_m": 1.5,
                           "period_s": 10, "swell_dir": 280, "wind_speed": 5,
                           "wind_dir": 90, "confidence": "high"})
        days.append({"date": date, "parts": dparts,
                     "height_min": 1.0, "height_max": 1.8})
        # one representative hour for the "current" logic
        hours.append({"time": f"{date}T12:00:00+00:00", "score": max(parts),
                      "label": "Fair", "swell": {"height_m": 1.5, "period_s": 10},
                      "wind": {"relation": "offshore"}})
    return {"days": days, "hours": hours}


def test_summary_has_sections_and_verdict():
    fc = _fc_days({"2026-09-20": [4, 4, 3], "2026-09-21": [2, 2, 2]})
    out = summary.build_summary([("Lahinch", fc)])
    assert "verdict" in out and out["current"] and out["best"] and out["narrative"]


def test_summary_quiet_week_when_all_poor():
    fc = _fc_days({"2026-09-20": [2, 2, 1], "2026-09-21": [1, 2, 2]})
    out = summary.build_summary([("Lahinch", fc)])
    assert "quiet spell" in out["verdict"].lower()


def test_summary_good_day_count_from_data():
    # 2 good days, 1 poor -> narrative should reflect good days exist
    fc = _fc_days({"2026-09-20": [4, 4, 4], "2026-09-21": [1, 1, 1],
                   "2026-09-22": [4, 3, 4]})
    out = summary.build_summary([("Lahinch", fc)])
    assert "Pick of the week" in out["verdict"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")
