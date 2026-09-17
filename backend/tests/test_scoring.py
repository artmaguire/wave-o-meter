"""Sanity tests for the scoring engine against real spot data."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import scoring  # noqa: E402
from app.spots import get_spot, load_spots  # noqa: E402


def test_spots_load_and_order():
    spots = load_spots()
    assert len(spots) == 10
    # Clare first (SDD §11).
    assert spots[0].county == "Clare"
    counties = [s.county for s in spots]
    # counties appear grouped in Clare, Sligo, Mayo, Kerry order
    order_seen = [c for i, c in enumerate(counties) if i == 0 or counties[i - 1] != c]
    assert order_seen == ["Clare", "Sligo", "Mayo", "Kerry"]


def test_flat_is_no_surf():
    lahinch = get_spot("lahinch")
    r = scoring.score_hour(
        lahinch, wave_height_m=0.2, wave_period_s=14, wave_from_deg=270,
        wind_speed_ms=2, wind_from_deg=90, tide_state="mid",
    )
    assert r.flat is True
    assert r.score == 0.0
    assert r.label == "No surf"


def test_perfect_conditions_high_score():
    lahinch = get_spot("lahinch")  # swell 225-315, offshore 45-100, low-mid
    r = scoring.score_hour(
        lahinch, wave_height_m=2.5, wave_period_s=14, wave_from_deg=270,
        wind_speed_ms=8, wind_from_deg=70, tide_state="low",
    )
    assert r.score >= 4.0, f"expected Good+, got {r.score} ({r.label})"
    assert r.label in ("Good", "Very good")


def test_onshore_wind_tanks_score():
    lahinch = get_spot("lahinch")
    offshore = scoring.score_hour(
        lahinch, wave_height_m=2.5, wave_period_s=14, wave_from_deg=270,
        wind_speed_ms=12, wind_from_deg=70, tide_state="low",
    )
    onshore = scoring.score_hour(
        lahinch, wave_height_m=2.5, wave_period_s=14, wave_from_deg=270,
        wind_speed_ms=12, wind_from_deg=250, tide_state="low",
    )
    assert onshore.score < offshore.score
    assert onshore.wind_factor < offshore.wind_factor


def test_reef_pickier_on_direction_than_beach():
    reef = get_spot("easkey_left")
    beach = get_spot("lahinch")
    # a swell 60 deg off each spot's window edge
    off_reef = scoring._swell_dir_factor(
        (reef.optimal_swell_dir[0] - 60) % 360, reef)
    off_beach = scoring._swell_dir_factor(
        (beach.optimal_swell_dir[0] - 60) % 360, beach)
    assert off_reef < off_beach


def test_angular_distance_wrap():
    assert scoring.angular_distance(350, 10) == 20
    assert scoring.angular_distance(10, 350) == 20
    assert scoring.angular_distance(0, 180) == 180


def test_label_banding():
    assert scoring.label_for(0.0) == "No surf"
    assert scoring.label_for(2.6) == "Fair"
    assert scoring.label_for(4.5) == "Very good"


def test_windsea_penalised_vs_clean_groundswell():
    lahinch = get_spot("lahinch")
    common = dict(wave_height_m=2.0, wave_period_s=13, wave_from_deg=270,
                  wind_speed_ms=5, wind_from_deg=70, tide_state="low")
    clean = scoring.score_hour(lahinch, **common,
                               swell_height_m=1.9, wind_wave_height_m=0.3)
    messy = scoring.score_hour(lahinch, **common,
                               swell_height_m=0.6, wind_wave_height_m=1.6)
    assert messy.score < clean.score
    assert messy.clean_factor < clean.clean_factor


def test_gusty_wind_trims_score():
    lahinch = get_spot("lahinch")
    common = dict(wave_height_m=2.0, wave_period_s=13, wave_from_deg=270,
                  wind_speed_ms=6, wind_from_deg=70, tide_state="low")
    steady = scoring.score_hour(lahinch, **common, gust_ms=7)
    gusty = scoring.score_hour(lahinch, **common, gust_ms=20)
    assert gusty.wind_factor < steady.wind_factor


def test_too_big_penalised():
    lahinch = get_spot("lahinch")  # workable to ~3.0 m
    common = dict(wave_period_s=13, wave_from_deg=270, wind_speed_ms=5,
                  wind_from_deg=70, tide_state="low")
    good = scoring.score_hour(lahinch, wave_height_m=2.8, **common)
    huge = scoring.score_hour(lahinch, wave_height_m=7.0, **common)
    assert huge.score < good.score


def test_reef_needs_longer_period():
    reef = get_spot("easkey_left")
    beach = get_spot("lahinch")
    # short-period 7s swell: reef should score its size-base lower than beach
    reef_pq = scoring._period_quality(7.0, reef)
    beach_pq = scoring._period_quality(7.0, beach)
    assert reef_pq < beach_pq


def test_get_spot_unknown_returns_none():
    assert get_spot("does-not-exist") is None


def test_flat_when_below_workable_min():
    lahinch = get_spot("lahinch")  # workable from ~0.8 m
    r = scoring.score_hour(
        lahinch, wave_height_m=0.2, wave_period_s=12, wave_from_deg=270,
        wind_speed_ms=4, wind_from_deg=70, tide_state="mid")
    assert r.flat is True and r.score == 0.0


def test_score_clamped_0_to_5():
    lahinch = get_spot("lahinch")
    r = scoring.score_hour(
        lahinch, wave_height_m=2.5, wave_period_s=14, wave_from_deg=270,
        wind_speed_ms=6, wind_from_deg=70, tide_state="low")
    assert 0.0 <= r.score <= 5.0


if __name__ == "__main__":
    # allow running without pytest
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")
