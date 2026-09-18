"""Best-surf-window detection for a day (SDD §6/§11).

Lives in the backend (next to scoring, and unit-tested) rather than the
frontend, and is SELF-CALIBRATING: window membership is defined relative to the
day's own peak score, not an absolute cutoff. That means it never needs
re-tuning when the scoring distribution shifts — a change to scoring.py can't
silently make the grouping too lenient or too strict.

A "window" is a run of consecutive daylight hours that are:
  * genuinely worth surfing (>= MIN_PEAK on the day's best), and
  * close to the day's peak (within REL_OF_PEAK of it),
so only the actually-good part of the day is highlighted. Adjacent hours split
into separate windows when they differ by more than STEP (a real lull between
two peaks), and windows clearly worse than the day's best are dropped.
"""

from __future__ import annotations

MIN_PEAK = 3.0        # a day must reach at least Fair somewhere to have a window
REL_OF_PEAK = 0.4     # hours within this of the day's peak are "in the window"
STEP = 0.6            # adjacent hours differing by more than this split
MAX_WINDOWS = 3


def _hour(iso: str) -> int:
    return int(iso[11:13])


def find_windows(day_hours: list[dict], sunrise_iso: str | None,
                 sunset_iso: str | None) -> list[dict]:
    """Return best surf windows for one day's hourly rows.

    day_hours: the day's hourly dicts (each with 'time' and 'score').
    Only daylight hours (between sunrise and sunset) are considered.
    Each window: {start, end, peak_score, peak_time} (times are ISO strings).
    """
    rise = _hour(sunrise_iso) if sunrise_iso else 6
    set_ = _hour(sunset_iso) if sunset_iso else 21
    hours = [h for h in day_hours
             if h.get("score") is not None and not h.get("missing")
             and rise <= _hour(h["time"]) <= set_]
    if not hours:
        return []
    hours.sort(key=lambda h: h["time"])

    peak = max(h["score"] for h in hours)
    if peak < MIN_PEAK:
        return []                       # nothing genuinely worth it today

    # threshold is relative to the day's own peak -> self-calibrating
    thresh = max(MIN_PEAK, peak - REL_OF_PEAK)

    windows, run = [], []

    def flush():
        if run:
            pk = max(run, key=lambda h: h["score"])
            windows.append({
                "start": run[0]["time"], "end": run[-1]["time"],
                "peak_score": round(pk["score"], 2), "peak_time": pk["time"],
            })

    for h in hours:
        if h["score"] < thresh:
            flush(); run = []
            continue
        prev = run[-1] if run else None
        consecutive = prev and _hour(h["time"]) - _hour(prev["time"]) == 1
        similar = prev and abs(h["score"] - prev["score"]) <= STEP
        if consecutive and similar:
            run.append(h)
        else:
            flush(); run = [h]
    flush()

    windows.sort(key=lambda w: w["peak_score"], reverse=True)
    return windows[:MAX_WINDOWS]
