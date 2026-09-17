"""Live end-to-end pipeline check (hits Open-Meteo). Run manually.

fetch -> tide classify -> score -> confidence, for one real spot.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import confidence, openmeteo, scoring, tide  # noqa: E402
from app.spots import get_spot  # noqa: E402


def main():
    spot = get_spot("lahinch")
    print(f"Fetching {spot.name} ({spot.lat},{spot.lon}) ...")
    fc = openmeteo.fetch_spot_forecast(spot.lat, spot.lon)
    print(f"  {len(fc.times)} hours; "
          f"first {fc.times[0]:%Y-%m-%d %H:%M} last {fc.times[-1]:%Y-%m-%d %H:%M}")

    # tide classification
    sea = {t: h for t, h in zip(fc.times, fc.sea_level, strict=False) if h is not None}
    tide_state = tide.classify_day(sea)

    # score first 6 hours + a couple of long-range hours
    print("\n  hour                 Hs   Tp  dir  wind        tide  rating")
    idxs = list(range(6)) + [24 * 5, 24 * 10]  # now-ish, day6, day11
    for i in idxs:
        if i >= len(fc.times):
            continue
        t = fc.times[i]
        hs = fc.wave_height[i]
        tp = fc.wave_period[i]
        wd = fc.wave_direction[i]
        ws = fc.wind_speed[i]
        wdir = fc.wind_direction[i]
        ts = tide_state.get(t, "mid")
        if None in (hs, tp, wd, ws, wdir):
            print(f"  {t:%Y-%m-%d %H:%M}  (missing data)")
            continue
        r = scoring.score_hour(
            spot, wave_height_m=hs, wave_period_s=tp, wave_from_deg=wd,
            wind_speed_ms=ws, wind_from_deg=wdir, tide_state=ts,
        )
        models = [fc.spread_heights[m][i] for m in fc.spread_heights]
        conf, spread = confidence.confidence_for_hour(models)
        spread_s = f"{spread:.2f}" if spread is not None else "  - "
        print(f"  {t:%Y-%m-%d %H:%M}  {hs:4.1f} {tp:4.0f} {wd:4.0f}  "
              f"{ws:4.1f}m/s {wdir:3.0f}  {ts:4s}  {r.score:.2f} {r.label:10s} "
              f"conf={conf} spread={spread_s}")

    assert len(fc.times) >= 24 * 11, "expected ~12 days of data"
    print("\nOK: full pipeline ran on live data.")


if __name__ == "__main__":
    main()
