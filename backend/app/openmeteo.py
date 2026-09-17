"""Open-Meteo client (SDD 4).

Fetches, for a spot's lat/lon:
  - wave height/period/direction for ECMWF (primary) + GWAM/EWAM (spread)
  - sea_level_height_msl (tide) from the marine API
  - wind speed/direction from the forecast API

All endpoints validated in the feasibility spike. No API key required.
Uses stdlib urllib to keep the data layer dependency-free.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from . import config


class OpenMeteoError(RuntimeError):
    pass


# Shared httpx client. httpx is far more reliable than stdlib urllib on flaky
# links (WSL -> Open-Meteo), with explicit connect/read timeouts and connection
# pooling. local_address="0.0.0.0" forces IPv4 (many WSL/home-server networks
# resolve Open-Meteo to IPv6 but have no IPv6 route -> "Network is unreachable").
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    # Double-checked locking: the client is created once and shared across the
    # scheduler + request threads. httpx.Client is thread-safe once built; the
    # lock only guards construction so concurrent first calls don't race.
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                transport = httpx.HTTPTransport(
                    retries=config.HTTP_RETRIES,
                    local_address="0.0.0.0" if config.FORCE_IPV4 else None,
                )
                _client = httpx.Client(
                    timeout=httpx.Timeout(config.HTTP_TIMEOUT_S, connect=10.0),
                    transport=transport,
                    headers={"User-Agent": "wave-o-meter/0.1"},
                    follow_redirects=True,
                )
    return _client


def _get(url: str) -> dict:
    """GET with connection-level retries + an app-level retry for slow links."""
    last_err = None
    for attempt in range(config.HTTP_RETRIES):
        try:
            resp = _get_client().get(url)
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("error"):
                raise OpenMeteoError(payload.get("reason", "Open-Meteo error"))
            return payload
        except OpenMeteoError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < config.HTTP_RETRIES - 1:
                time.sleep(config.HTTP_RETRY_BACKOFF_S * (attempt + 1))
    raise OpenMeteoError(f"request failed after {config.HTTP_RETRIES} tries: "
                         f"{url[:80]} -> {last_err}")


_TZ = ZoneInfo(config.TIMEZONE)


def _parse_times(times: list[str]) -> list[datetime]:
    # Open-Meteo returns local wall-clock times (no offset) when a timezone is
    # requested. Attach the zone so each timestamp is DST-correct and absolute.
    return [datetime.fromisoformat(t).replace(tzinfo=_TZ) for t in times]


@dataclass
class SpotForecast:
    """Raw hourly forecast for one spot, keyed by UTC hour."""
    times: list[datetime]
    # primary (ECMWF) conditions
    wave_height: list[float | None]
    wave_period: list[float | None]
    wave_direction: list[float | None]
    sea_level: list[float | None]
    wind_speed: list[float | None]     # m/s
    wind_direction: list[float | None]
    # swell / wind-wave separation + sea temp (base marine vars, not model-split)
    swell_height: list[float | None]
    swell_period: list[float | None]
    swell_direction: list[float | None]
    wind_wave_height: list[float | None]
    sea_temp: list[float | None]       # °C
    wind_gust: list[float | None]      # m/s
    # daily (date-keyed): sunrise/sunset ISO, weather_code, uv
    daily: dict[str, dict]
    # spread models: model_id -> wave_height series aligned to `times`
    spread_heights: dict[str, list[float | None]]


def fetch_marine(lat: float, lon: float) -> dict:
    """Wave (multi-model) + tide from the marine API."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "wave_height", "wave_period", "wave_direction",
        ]),
        "models": ",".join(config.ALL_WAVE_MODELS),
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }
    url = f"{config.MARINE_API}?{urllib.parse.urlencode(params)}"
    return _get(url)


def fetch_base(lat: float, lon: float) -> dict:
    """Base marine variables (NOT model-split): tide, swell/wind-wave separation,
    and sea temperature. These must be requested WITHOUT the models param —
    requesting them alongside wave models returns all-null."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "sea_level_height_msl",
            "swell_wave_height", "swell_wave_period", "swell_wave_direction",
            "wind_wave_height",
            "sea_surface_temperature",
        ]),
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }
    url = f"{config.MARINE_API}?{urllib.parse.urlencode(params)}"
    return _get(url)


def fetch_wind(lat: float, lon: float) -> dict:
    """Wind (m/s) hourly + daily sun times / weather code from the forecast API.
    Daily sun times ride along on this same call — no extra request."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "daily": "sunrise,sunset,weather_code,uv_index_max,temperature_2m_max,temperature_2m_min",
        "wind_speed_unit": "ms",
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }
    url = f"{config.FORECAST_API}?{urllib.parse.urlencode(params)}"
    return _get(url)


def _series(hourly: dict, key: str, n: int) -> list[float | None]:
    vals = hourly.get(key)
    if vals is None:
        return [None] * n
    return [float(v) if v is not None else None for v in vals]


def fetch_spot_forecast(lat: float, lon: float) -> SpotForecast:
    """Fetch + align marine and wind data for a spot.

    The three upstream calls (waves, sea level, wind) are independent, so run
    them concurrently to cut latency ~3x on slow links."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_marine = ex.submit(fetch_marine, lat, lon)
        f_base = ex.submit(fetch_base, lat, lon)
        f_wind = ex.submit(fetch_wind, lat, lon)
        marine = f_marine.result()
        base = f_base.result()
        wind = f_wind.result()

    m_hourly = marine.get("hourly", {})
    times = _parse_times(m_hourly.get("time", []))
    n = len(times)

    primary = config.PRIMARY_WAVE_MODEL
    wave_height = _series(m_hourly, f"wave_height_{primary}", n)
    wave_period = _series(m_hourly, f"wave_period_{primary}", n)
    wave_direction = _series(m_hourly, f"wave_direction_{primary}", n)

    # base marine vars (model-less request); align each by timestamp.
    b_hourly = base.get("hourly", {})
    b_times = _parse_times(b_hourly.get("time", []))

    def _aligned(key):
        by_t = dict(zip(b_times, _series(b_hourly, key, len(b_times))))
        return [by_t.get(t) for t in times]

    sea_level = _aligned("sea_level_height_msl")
    swell_height = _aligned("swell_wave_height")
    swell_period = _aligned("swell_wave_period")
    swell_direction = _aligned("swell_wave_direction")
    wind_wave_height = _aligned("wind_wave_height")
    sea_temp = _aligned("sea_surface_temperature")

    spread_heights: dict[str, list[float | None]] = {}
    for model in config.ALL_WAVE_MODELS:
        spread_heights[model] = _series(m_hourly, f"wave_height_{model}", n)

    # Align wind to the marine time index (both use forecast_days + GMT so they
    # should match; map by timestamp to be safe).
    w_hourly = wind.get("hourly", {})
    w_times = _parse_times(w_hourly.get("time", []))
    w_speed = _series(w_hourly, "wind_speed_10m", len(w_times))
    w_dir = _series(w_hourly, "wind_direction_10m", len(w_times))
    wind_speed_by_t = dict(zip(w_times, w_speed))
    wind_dir_by_t = dict(zip(w_times, w_dir))
    wind_speed = [wind_speed_by_t.get(t) for t in times]
    wind_direction = [wind_dir_by_t.get(t) for t in times]
    w_gust = _series(w_hourly, "wind_gusts_10m", len(w_times))
    gust_by_t = dict(zip(w_times, w_gust))
    wind_gust = [gust_by_t.get(t) for t in times]

    # daily block keyed by date -> {sunrise, sunset, weather_code, uv}
    w_daily = wind.get("daily", {})
    daily = {}
    for j, date in enumerate(w_daily.get("time", [])):
        daily[date] = {
            "sunrise": (w_daily.get("sunrise") or [None])[j]
                       if j < len(w_daily.get("sunrise", [])) else None,
            "sunset": (w_daily.get("sunset") or [None])[j]
                      if j < len(w_daily.get("sunset", [])) else None,
            "weather_code": (w_daily.get("weather_code") or [None])[j]
                            if j < len(w_daily.get("weather_code", [])) else None,
            "uv": (w_daily.get("uv_index_max") or [None])[j]
                  if j < len(w_daily.get("uv_index_max", [])) else None,
            "air_max": (w_daily.get("temperature_2m_max") or [None])[j]
                       if j < len(w_daily.get("temperature_2m_max", [])) else None,
        }

    return SpotForecast(
        times=times,
        wave_height=wave_height,
        wave_period=wave_period,
        wave_direction=wave_direction,
        sea_level=sea_level,
        wind_speed=wind_speed,
        wind_direction=wind_direction,
        swell_height=swell_height,
        swell_period=swell_period,
        swell_direction=swell_direction,
        wind_wave_height=wind_wave_height,
        sea_temp=sea_temp,
        wind_gust=wind_gust,
        daily=daily,
        spread_heights=spread_heights,
    )


def fetch_weather(lat: float, lon: float) -> dict:
    """Daily general weather for the surf-news narrative (temp, rain, max wind).
    One call for a central point powers the regional summary."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join([
            "temperature_2m_max", "temperature_2m_min",
            "precipitation_sum", "wind_speed_10m_max", "wind_gusts_10m_max",
            "weather_code", "sunrise", "sunset", "uv_index_max",
        ]),
        "forecast_days": config.FORECAST_DAYS,
        "wind_speed_unit": "ms",
        "timezone": config.TIMEZONE,
    }
    url = f"{config.FORECAST_API}?{urllib.parse.urlencode(params)}"
    return _get(url)
