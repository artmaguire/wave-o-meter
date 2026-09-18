"""Tests for the self-calibrating surf-window detector (app/windows.py).

The key property: windows are defined RELATIVE to each day's peak, so the same
shape of day yields the same windows regardless of the overall score level —
that's what stops the grouping drifting when scoring.py changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import windows  # noqa: E402


def _day(scores, day="2026-09-20"):
    return [{"time": f"{day}T{h:02d}:00", "score": s}
            for h, s in enumerate(scores)]


SUN = ("2026-09-20T07:00", "2026-09-20T19:00")


def test_no_window_on_a_poor_day():
    scores = [0] * 7 + [2.0, 2.2, 2.4, 2.5, 2.4] + [0] * 12
    assert windows.find_windows(_day(scores), *SUN) == []


def test_split_day_yields_two_windows():
    # good morning, midday lull, good evening
    scores = [0] * 7 + [3.9, 4.0, 3.8, 2.5, 2.4, 2.6, 3.7, 3.9, 4.0, 3.8] + [0] * 7
    w = windows.find_windows(_day(scores), *SUN)
    assert len(w) == 2
    starts = sorted(int(x["start"][11:13]) for x in w)
    assert starts == [7, 13]


def test_window_is_the_best_part_not_the_whole_day():
    # builds all day; window should be the afternoon peak, not from 7am
    scores = [0] * 7 + [3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.2, 4.4, 4.5, 4.5] + [0] * 7
    w = windows.find_windows(_day(scores), *SUN)
    assert len(w) == 1
    assert int(w[0]["start"][11:13]) >= 12   # only the strong afternoon


def test_self_calibrating_same_shape_different_level():
    """Same-shaped day at two score levels -> same window boundaries.

    This is the anti-drift guarantee: if scoring shifts everything up or down,
    the windows track the shape, not an absolute cutoff.
    """
    shape = [0.0, 0.2, 0.5, 1.0, 0.5, 0.2]      # a single hump
    lo = [0] * 7 + [3.0 + x for x in shape] + [0] * 11
    hi = [0] * 7 + [4.0 + x for x in shape] + [0] * 11
    wl = windows.find_windows(_day(lo), *SUN)
    wh = windows.find_windows(_day(hi), *SUN)
    assert wl and wh
    assert (wl[0]["start"][11:], wl[0]["end"][11:]) == \
           (wh[0]["start"][11:], wh[0]["end"][11:])


def test_uniformly_excellent_day_is_one_long_window():
    scores = [0] * 7 + [4.0] * 12 + [0] * 5
    w = windows.find_windows(_day(scores), *SUN)
    assert len(w) == 1
    assert int(w[0]["start"][11:13]) == 7


def test_daylight_only():
    # a 4.0 at 04:00 (pre-dawn) must be ignored
    scores = [0, 0, 0, 0, 4.0, 0, 0] + [0] * 17
    assert windows.find_windows(_day(scores), *SUN) == []


def test_capped_at_three_windows():
    # four separated humps -> at most 3 returned
    scores = [0] * 6 + [3.8, 2.0, 3.8, 2.0, 3.8, 2.0, 3.8] + [0] * 11
    w = windows.find_windows(_day(scores), *SUN)
    assert len(w) <= 3


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")
