"""Tests for security-relevant + previously-untested pure helpers:
_client_ip (X-Forwarded-For trust), accuracy._stats, sessions clamping,
forecast helpers, and cache staleness.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, peer, xff=None):
        self.client = _FakeClient(peer) if peer else None
        self._headers = {}
        if xff is not None:
            self._headers["x-forwarded-for"] = xff

    @property
    def headers(self):
        return self._headers


def _main_with_proxies(proxies=""):
    os.environ["TRUSTED_PROXIES"] = proxies
    os.environ["GATE_SECRET"] = "t"; os.environ["GATE_ANSWER"] = "x"
    from app import config, main
    importlib.reload(config)
    importlib.reload(main)
    return main


# --- _client_ip X-Forwarded-For trust ---

def test_client_ip_uses_peer_when_no_proxy_trusted():
    main = _main_with_proxies("")  # trust nobody
    # even with a spoofed XFF, we must use the direct peer
    r = _FakeRequest("203.0.113.9", xff="1.1.1.1")
    assert main._client_ip(r) == "203.0.113.9"


def test_client_ip_ignores_xff_from_untrusted_peer():
    main = _main_with_proxies("10.0.0.1")  # only trust 10.0.0.1
    r = _FakeRequest("203.0.113.9", xff="9.9.9.9")  # peer not the proxy
    assert main._client_ip(r) == "203.0.113.9"


def test_client_ip_trusts_last_xff_hop_from_proxy():
    main = _main_with_proxies("10.0.0.1")
    # request arrives from the trusted proxy; XFF last hop is the real client
    r = _FakeRequest("10.0.0.1", xff="1.1.1.1, 2.2.2.2, 203.0.113.5")
    assert main._client_ip(r) == "203.0.113.5"


def test_client_ip_spoof_cannot_rotate_when_untrusted():
    """The bypass we fixed: attacker sends different XFF each time but the
    rate-limit key stays the (constant) peer IP."""
    main = _main_with_proxies("")
    keys = {main._client_ip(_FakeRequest("203.0.113.9", xff=f"{i}.{i}.{i}.{i}"))
            for i in range(5)}
    assert keys == {"203.0.113.9"}  # all map to one key -> lockout still works


# --- accuracy._stats ---

def test_accuracy_stats_perfect_match():
    from app import accuracy
    hrs = {i: float(i) for i in range(10)}
    st = accuracy._stats(hrs, hrs)
    assert st["mae"] == 0.0 and round(st["corr"], 2) == 1.0 and st["n"] == 10


def test_accuracy_stats_constant_offset():
    from app import accuracy
    obs = {i: float(i) for i in range(10)}
    pred = {i: float(i) + 0.5 for i in range(10)}
    st = accuracy._stats(pred, obs)
    assert st["mae"] == 0.5 and round(st["corr"], 2) == 1.0


def test_accuracy_stats_too_few_points():
    from app import accuracy
    assert accuracy._stats({1: 1.0}, {1: 1.0}) is None


# --- sessions clamping / truncation ---

def test_sessions_rating_clamped_and_notes_truncated():
    os.environ["DB_PATH"] = "/tmp/wom_test_sessions.sqlite3"
    for f in ("/tmp/wom_test_sessions.sqlite3", "/tmp/wom_test_sessions.sqlite3-wal",
              "/tmp/wom_test_sessions.sqlite3-shm"):
        try:
            os.remove(f)
        except OSError:
            pass
    from app import config, db, sessions
    importlib.reload(config); importlib.reload(db); importlib.reload(sessions)
    sessions.init_db()
    # rating clamped to 0-5; notes capped at 1000 chars
    hi = sessions.add("lahinch", "2026-09-20", 9, "x" * 1500)
    assert hi["rating"] == 5 and len(hi["notes"]) == 1000
    lo = sessions.add("lahinch", "2026-09-20", -3, "")
    assert lo["rating"] == 0
    assert sessions.delete(hi["id"]) is True
    assert sessions.delete(999999) is False


# --- forecast helpers ---

def test_sessions_rich_fields_and_vocab_filtering():
    os.environ["DB_PATH"] = "/tmp/wom_test_rich.sqlite3"
    for suf in ("", "-wal", "-shm"):
        try:
            os.remove("/tmp/wom_test_rich.sqlite3" + suf)
        except OSError:
            pass
    from app import config, db, sessions
    importlib.reload(config); importlib.reload(db); importlib.reload(sessions)
    sessions.init_db()
    row = sessions.add(
        "lahinch", "2026-09-20", 4, "peaky lefts",
        time_of_day="08:00", wave_size="chest", wave_quality="clean",
        wind="light offshore", tide="mid", tide_movement="rising",
        crowd="a few out", board="shortboard", wetsuit="4/3 + booties",
        length="1-2 h")
    assert row["wave_size"] == "chest" and row["board"] == "shortboard"
    assert row["tide_movement"] == "rising" and row["time_of_day"] == "08:00"
    # unknown vocabulary values are dropped, keeping the data analysable
    bad = sessions.add("lahinch", "2026-09-20", 3, "", wave_size="enormous",
                       wind="hurricane", board="jetski")
    assert bad["wave_size"] == "" and bad["wind"] == "" and bad["board"] == ""
    # round-trips through the DB
    listed = sessions.list_for("lahinch")
    assert any(r["wave_quality"] == "clean" for r in listed)


def test_session_vocab_exposed_for_dropdowns():
    from app import sessions
    for key in ("wave_size", "wave_quality", "wind", "tide", "tide_movement",
                "crowd", "board", "wetsuit", "length", "rating"):
        assert key in sessions.VOCAB and sessions.VOCAB[key]


def test_spot_profile_assembles_all_fields():
    from app import forecast
    from app.spots import get_spot
    prof = forecast._spot_profile(get_spot("easkey_right"))
    # stored profile fields + derived ones both present
    for k in ("wave_direction", "bottom", "wave_quality", "power",
              "tide_movement", "break_type", "skill", "swell_dir",
              "wind_dir", "tide_position", "size_ft"):
        assert k in prof and prof[k], f"missing {k}"
    assert prof["break_type"] == "point"          # from metadata
    assert "-" in prof["swell_dir"]               # compass range e.g. WSW-NNE
    assert prof["size_ft"].endswith("ft")


def test_wetsuit_thresholds_irish_calibration():
    from app import forecast
    # Ireland: a 4/3 is the year-round workhorse — never default to 3/2
    assert "4/3" in forecast.wetsuit_for(16)
    assert "4/3" in forecast.wetsuit_for(14)
    assert forecast.wetsuit_for(None) is None
    # cold water steps up to 5/4 hooded
    assert "5/4" in forecast.wetsuit_for(10)
    assert "hooded" in forecast.wetsuit_for(8)


def test_wave_power_formula_and_bands():
    from app import forecast
    # power scales with H^2 * T: doubling height ~4x power, doubling period ~2x
    p1 = forecast.wave_power_kw_m(1.0, 10.0)
    p2 = forecast.wave_power_kw_m(2.0, 10.0)
    p3 = forecast.wave_power_kw_m(1.0, 20.0)
    assert round(p2 / p1) == 4
    assert round(p3 / p1) == 2
    assert forecast.wave_power_kw_m(None, 10) is None
    assert forecast.wave_power_kw_m(1.0, None) is None
    # bands ascend sensibly
    assert forecast.power_label(forecast.wave_power_kw_m(0.8, 8)) == "gentle"
    assert forecast.power_label(forecast.wave_power_kw_m(2.5, 11)) == "punchy"
    assert forecast.power_label(forecast.wave_power_kw_m(4.0, 14)) == "heavy"
    assert forecast.power_label(None) is None


def test_compass_and_none():
    from app import forecast
    assert forecast.compass(0) == "N"
    assert forecast.compass(90) == "E"
    assert forecast.compass(None) is None


def test_rating_trend_over_days():
    from app import forecast

    def days(day_bests):
        # each day -> parts carrying the day's best score
        return [{"parts": [{"score": b}]} for b in day_bests]

    # today low, next days higher -> improving
    assert forecast._rating_trend(days([2.0, 3.0, 4.0])) == "improving"
    # today high, next days lower -> dropping
    assert forecast._rating_trend(days([4.0, 3.0, 2.0])) == "dropping"
    # flat week -> steady
    assert forecast._rating_trend(days([3.0, 3.0, 3.0])) == "steady"


# --- cache staleness ---

def test_cache_is_stale():
    os.environ["DB_PATH"] = "/tmp/wom_test_cache.sqlite3"
    os.environ["CACHE_STALE_MIN"] = "60"
    for f in ("/tmp/wom_test_cache.sqlite3", "/tmp/wom_test_cache.sqlite3-wal",
              "/tmp/wom_test_cache.sqlite3-shm"):
        try:
            os.remove(f)
        except OSError:
            pass
    from app import cache, config, db
    importlib.reload(config); importlib.reload(db); importlib.reload(cache)
    cache.init_db()
    assert cache.is_stale("nope") is True  # never cached
    cache.put("s", {"x": 1})
    assert cache.is_stale("s") is False    # just written


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")
