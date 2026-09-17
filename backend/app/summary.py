"""Surf-weather-news style summary across all spots (home 'Summary' button).

Reads like a personal forecaster's briefing:
  - Right now: best spots + conditions
  - This week's best windows
  - A day-by-day narrative of swell evolution + weather impact
  - Where/when things build or drop, and which spots benefit

Pure aggregation over already-computed forecasts + one regional weather fetch.
"""

from __future__ import annotations

from datetime import datetime, timezone

GOOD = 3.0
VGOOD = 4.0


# Surf (face) height: ~0.6x significant wave height, matching the frontend.
# Surfers quote the breaking face, not raw open-ocean Hs. Display only.
_SURF_FACE_FACTOR = 0.6


def _ft(m):
    return round(m * 3.281 * _SURF_FACE_FACTOR) if m is not None else None


def _day_label(date_str: str) -> str:
    return datetime.fromisoformat(date_str + "T12:00:00").strftime("%A")


_PART = {"morning": "morning", "afternoon": "midday", "evening": "evening"}


def _spot_day_best(fc, date):
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
            series.append(None); continue
        hs = [p.get("height_m") for p in day["parts"] if p.get("height_m")]
        series.append(sum(hs) / len(hs) if hs else None)
    return series


def build_summary(spots_forecasts, weather=None) -> dict:
    now = datetime.now(timezone.utc)
    dates = [d["date"] for d in spots_forecasts[0][1].get("days", [])] if spots_forecasts else []

    # --- current conditions ---
    current = []
    for name, fc in spots_forecasts:
        hours = [h for h in fc.get("hours", []) if not h.get("missing")]
        if not hours:
            continue
        cur = min(hours, key=lambda h: abs(datetime.fromisoformat(h["time"]) - now))
        current.append((name, cur))
    current.sort(key=lambda x: (x[1].get("score") or 0), reverse=True)

    current_lines = []
    for name, h in current[:3]:
        current_lines.append(
            f"{name}: {h['label']} ({round(h['score'])}/5), "
            f"{_ft(h['swell']['height_m'])} ft @ {h['swell']['period_s']}s, "
            f"{h['wind']['relation']} wind")

    top_now = current[0] if current else None

    # --- best windows this week ---
    windows = []
    for name, fc in spots_forecasts:
        for day in fc.get("days", [])[:7]:
            for p in day["parts"]:
                if (p.get("score") or 0) >= GOOD:
                    windows.append((p["score"], name, day["date"], p["part"], p.get("height_m")))
    windows.sort(reverse=True, key=lambda w: w[0])
    best_lines, seen = [], set()
    for score, name, date, part, h in windows:
        key = (name, date, part)
        if key in seen:
            continue
        seen.add(key)
        best_lines.append(
            f"{name} — {_day_label(date)} {_PART[part]}: "
            f"{'Very good' if score >= VGOOD else 'Good'} ({round(score)}/5), {_ft(h)} ft")
        if len(best_lines) >= 5:
            break

    # --- narrative: swell evolution + weather, per day ---
    # regional swell trend from the strongest-exposed spot (first with data)
    ref_fc = spots_forecasts[0][1] if spots_forecasts else {}
    trend = _trend(ref_fc, dates)

    wx_daily = (weather or {}).get("daily", {})
    wx_dates = wx_daily.get("time", [])
    wx_rain = wx_daily.get("precipitation_sum", [])
    wx_wind = wx_daily.get("wind_speed_10m_max", [])
    wx_gust = wx_daily.get("wind_gusts_10m_max", [])
    wx_tmax = wx_daily.get("temperature_2m_max", [])
    wx = {d: i for i, d in enumerate(wx_dates)}

    narrative = []
    for idx, date in enumerate(dates[:10]):
        parts_txt = []

        # swell evolution vs previous day
        h = trend[idx]
        if h is not None and idx > 0 and trend[idx - 1] is not None:
            diff = h - trend[idx - 1]
            if diff > 0.4:
                parts_txt.append(f"swell building to ~{_ft(h)} ft")
            elif diff < -0.4:
                parts_txt.append(f"swell easing to ~{_ft(h)} ft")
            else:
                parts_txt.append(f"swell holding ~{_ft(h)} ft")
        elif h is not None:
            parts_txt.append(f"~{_ft(h)} ft of swell")

        # which spots are good
        good_spots = []
        for name, fc in spots_forecasts:
            r = _spot_day_best(fc, date)
            if r and r[0] >= GOOD:
                good_spots.append((name, r[0], r[1]))
        good_spots.sort(key=lambda x: x[1], reverse=True)

        # weather impact
        wi = wx.get(date)
        if wi is not None and wi < len(wx_wind):
            wind = wx_wind[wi]; gust = wx_gust[wi] if wi < len(wx_gust) else None
            rain = wx_rain[wi] if wi < len(wx_rain) else 0
            tmax = wx_tmax[wi] if wi < len(wx_tmax) else None
            wtxt = []
            if wind is not None:
                if wind >= 11:
                    wtxt.append(f"strong winds (to {round(gust or wind)} m/s gusts) — likely messy/blown out")
                elif wind >= 7:
                    wtxt.append(f"moderate wind ({round(wind)} m/s)")
                else:
                    wtxt.append(f"light winds ({round(wind)} m/s) — cleaner faces")
            if rain and rain >= 5:
                wtxt.append("wet")
            if tmax is not None:
                wtxt.append(f"{round(tmax)}°C")
            if wtxt:
                parts_txt.append("; ".join(wtxt))

        # assemble
        headline = f"{_day_label(date)}: " + ", ".join(parts_txt) if parts_txt else f"{_day_label(date)}:"
        if good_spots:
            names = ", ".join(n for n, _, _ in good_spots[:3])
            verdict = "Very good" if good_spots[0][1] >= VGOOD else "Good"
            headline += f". {verdict} at {names}"
        else:
            headline += ". Nothing standout — small or off."
        narrative.append(headline)

    # --- overall verdict line ---
    good_days = [n for n in narrative if "Good at" in n or "Very good at" in n]
    if best_lines and windows:
        peak = windows[0]
        verdict = (f"Pick of the week: {peak[1]} on {_day_label(peak[2])} "
                   f"{_PART[peak[3]]} ({round(peak[0])}/5). "
                   f"{len(good_days)} of the next 10 days have a surfable window.")
    else:
        verdict = "A quiet spell — nothing above Fair across the spots this week."

    if not current_lines:
        current_lines = ["No live conditions available."]
    if not best_lines:
        best_lines = ["Nothing above Fair in the next 7 days."]

    return {
        "generated_at": now.isoformat(),
        "verdict": verdict,
        "current": current_lines,
        "best": best_lines,
        "narrative": narrative,
    }
