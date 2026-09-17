"""Surf-weather-news style summary across all spots (home 'Summary' button).

Reads like a personal forecaster's briefing:
  - Right now: best spots + conditions
  - This week's best windows
  - A day-by-day narrative of swell evolution + weather impact
  - Where/when things build or drop, and which spots benefit

Pure aggregation over already-computed forecasts + one regional weather fetch.
`build_summary` is split into focused section builders (current / best windows /
narrative / verdict) so each piece is independently readable and testable.
"""

from __future__ import annotations

from datetime import datetime, timezone

# --- rating thresholds ---
GOOD = 3.0                 # Fair+ — worth a session
VGOOD = 4.0                # Good+ — a proper session

# --- narrative tuning (named so they're not magic numbers) ---
SWELL_TREND_M = 0.4        # per-day height change to call "building"/"easing"
WIND_STRONG_MS = 11.0      # >= this: likely messy / blown out
WIND_MODERATE_MS = 7.0     # >= this: moderate; below: light/clean
RAIN_WET_MM = 5.0          # daily precip to mention "wet"
MAX_BEST_WINDOWS = 5
NARRATIVE_DAYS = 10

# Surf (face) height: ~0.6x significant wave height, matching the frontend.
# Surfers quote the breaking face, not raw open-ocean Hs. Display only.
_SURF_FACE_FACTOR = 0.6

_PART = {"morning": "morning", "afternoon": "midday", "evening": "evening"}


def _ft(m):
    return round(m * 3.281 * _SURF_FACE_FACTOR) if m is not None else None


def _day_label(date_str: str) -> str:
    return datetime.fromisoformat(date_str + "T12:00:00").strftime("%A")


def _verdict_word(score: float) -> str:
    return "Very good" if score >= VGOOD else "Good"


def _spot_day_best(fc, date):
    """(best_score, best_part, day) for a spot on a date, or None."""
    day = next((d for d in fc.get("days", []) if d["date"] == date), None)
    if not day:
        return None
    scored = [(p.get("score") or 0, p) for p in day["parts"]]
    best_score, best_part = max(scored, key=lambda x: x[0])
    return best_score, best_part, day


def _trend(fc, dates):
    """Regional swell height per day (avg of dayparts) to describe evolution."""
    series = []
    for date in dates:
        day = next((d for d in fc.get("days", []) if d["date"] == date), None)
        if not day:
            series.append(None)
            continue
        hs = [p.get("height_m") for p in day["parts"] if p.get("height_m")]
        series.append(sum(hs) / len(hs) if hs else None)
    return series


def _good_spots_on(spots_forecasts, date):
    """Spots scoring GOOD+ on a date, sorted best-first: [(name, score, part)]."""
    out = []
    for name, fc in spots_forecasts:
        r = _spot_day_best(fc, date)
        if r and r[0] >= GOOD:
            out.append((name, r[0], r[1]))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


# --- section builders -------------------------------------------------------

def _current_section(spots_forecasts, now):
    """Top spots right now, ranked by the hour nearest to `now`."""
    current = []
    for name, fc in spots_forecasts:
        hours = [h for h in fc.get("hours", []) if not h.get("missing")]
        if not hours:
            continue
        cur = min(hours, key=lambda h: abs(datetime.fromisoformat(h["time"]) - now))
        current.append((name, cur))
    current.sort(key=lambda x: (x[1].get("score") or 0), reverse=True)

    lines = [
        f"{name}: {h['label']} ({round(h['score'])}/5), "
        f"{_ft(h['swell']['height_m'])} ft @ {h['swell']['period_s']}s, "
        f"{h['wind']['relation']} wind"
        for name, h in current[:3]
    ]
    return lines or ["No live conditions available."]


def _best_windows(spots_forecasts):
    """Strongest GOOD+ daypart sessions this week. Returns (lines, ranked)."""
    windows = []
    for name, fc in spots_forecasts:
        for day in fc.get("days", [])[:7]:
            for p in day["parts"]:
                if (p.get("score") or 0) >= GOOD:
                    windows.append(
                        (p["score"], name, day["date"], p["part"], p.get("height_m")))
    windows.sort(reverse=True, key=lambda w: w[0])

    lines, seen = [], set()
    for score, name, date, part, h in windows:
        key = (name, date, part)
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"{name} — {_day_label(date)} {_PART[part]}: "
            f"{_verdict_word(score)} ({round(score)}/5), {_ft(h)} ft")
        if len(lines) >= MAX_BEST_WINDOWS:
            break
    if not lines:
        lines = ["Nothing above Fair in the next 7 days."]
    return lines, windows


def _swell_phrase(trend, idx):
    h = trend[idx]
    if h is None:
        return None
    if idx > 0 and trend[idx - 1] is not None:
        diff = h - trend[idx - 1]
        if diff > SWELL_TREND_M:
            return f"swell building to ~{_ft(h)} ft"
        if diff < -SWELL_TREND_M:
            return f"swell easing to ~{_ft(h)} ft"
        return f"swell holding ~{_ft(h)} ft"
    return f"~{_ft(h)} ft of swell"


def _weather_phrase(wx_by_date, date):
    w = wx_by_date.get(date)
    if not w:
        return None
    bits = []
    wind = w.get("wind")
    if wind is not None:
        if wind >= WIND_STRONG_MS:
            gust = w.get("gust") or wind
            bits.append(f"strong winds (to {round(gust)} m/s gusts) — likely messy/blown out")
        elif wind >= WIND_MODERATE_MS:
            bits.append(f"moderate wind ({round(wind)} m/s)")
        else:
            bits.append(f"light winds ({round(wind)} m/s) — cleaner faces")
    if (w.get("rain") or 0) >= RAIN_WET_MM:
        bits.append("wet")
    if w.get("tmax") is not None:
        bits.append(f"{round(w['tmax'])}°C")
    return "; ".join(bits) if bits else None


def _weather_by_date(weather):
    daily = (weather or {}).get("daily", {})
    dates = daily.get("time", [])
    out = {}
    for i, d in enumerate(dates):
        out[d] = {
            "wind": _at(daily.get("wind_speed_10m_max"), i),
            "gust": _at(daily.get("wind_gusts_10m_max"), i),
            "rain": _at(daily.get("precipitation_sum"), i),
            "tmax": _at(daily.get("temperature_2m_max"), i),
        }
    return out


def _at(seq, i):
    return seq[i] if seq and i < len(seq) else None


def _narrative_section(spots_forecasts, dates, weather):
    """Day-by-day swell + weather narrative. Returns (lines, good_day_count)."""
    ref_fc = spots_forecasts[0][1] if spots_forecasts else {}
    trend = _trend(ref_fc, dates)
    wx_by_date = _weather_by_date(weather)

    lines, good_days = [], 0
    for idx, date in enumerate(dates[:NARRATIVE_DAYS]):
        parts = []
        sp = _swell_phrase(trend, idx)
        if sp:
            parts.append(sp)
        wp = _weather_phrase(wx_by_date, date)
        if wp:
            parts.append(wp)

        headline = f"{_day_label(date)}: " + ", ".join(parts) if parts else f"{_day_label(date)}:"
        good = _good_spots_on(spots_forecasts, date)
        if good:
            good_days += 1
            names = ", ".join(n for n, _, _ in good[:3])
            headline += f". {_verdict_word(good[0][1])} at {names}"
        else:
            headline += ". Nothing standout — small or off."
        lines.append(headline)
    return lines, good_days


def _verdict_line(windows, good_days):
    if not windows:
        return "A quiet spell — nothing above Fair across the spots this week."
    peak = windows[0]  # (score, name, date, part, height)
    return (f"Pick of the week: {peak[1]} on {_day_label(peak[2])} "
            f"{_PART[peak[3]]} ({round(peak[0])}/5). "
            f"{good_days} of the next {NARRATIVE_DAYS} days have a surfable window.")


def build_summary(spots_forecasts, weather=None) -> dict:
    now = datetime.now(timezone.utc)
    dates = ([d["date"] for d in spots_forecasts[0][1].get("days", [])]
             if spots_forecasts else [])

    current = _current_section(spots_forecasts, now)
    best, windows = _best_windows(spots_forecasts)
    narrative, good_days = _narrative_section(spots_forecasts, dates, weather)
    verdict = _verdict_line(windows, good_days)

    return {
        "generated_at": now.isoformat(),
        "verdict": verdict,
        "current": current,
        "best": best,
        "narrative": narrative,
    }
