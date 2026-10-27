import json
import logging
import urllib.request
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DAILY = "temperature_2m_max,temperature_2m_min,wind_speed_10m_max,rain_sum"


def _flight_date(timestamp_utc: Optional[str]) -> Optional[str]:
    if not timestamp_utc:
        return None
    try:
        return datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        logger.warning(f"Unparseable flight start time: {timestamp_utc!r}")
        return None


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "FlightMD/1.0"})
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_weather(lat: float, lon: float, timestamp_utc: Optional[str]) -> dict:
    """
    Daily weather for the flight's date and place from Open-Meteo. timestamp_utc is the
    ISO-8601 log start. Never raises: no date, no network or a bad answer all give the
    "unavailable" dict. Wind comes back in m/s.
    """
    unavailable = {
        "temperature_max_c": None,
        "temperature_min_c": None,
        "wind_speed_max_ms": None,
        "rain_sum_mm": None,
        "description": "Weather data unavailable",
    }
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return unavailable

    date = _flight_date(timestamp_utc)
    if not date:
        # never fall back to today: that's another day's weather
        return unavailable

    query = (
        f"latitude={lat:.4f}&longitude={lon:.4f}&start_date={date}&end_date={date}"
        f"&daily={DAILY}&timezone=auto"
    )
    # the archive lags a few days behind, the forcast API covers the recent past
    for base in ("https://archive-api.open-meteo.com/v1/archive", "https://api.open-meteo.com/v1/forecast"):
        try:
            daily = _get(f"{base}?{query}").get("daily") or {}
        except Exception as e:
            logger.warning(f"Open-Meteo request failed ({base}): {e}")
            continue

        temp_max = (daily.get("temperature_2m_max") or [None])[0]
        temp_min = (daily.get("temperature_2m_min") or [None])[0]
        wind_kmh = (daily.get("wind_speed_10m_max") or [None])[0]
        rain = (daily.get("rain_sum") or [None])[0]
        if temp_max is None and wind_kmh is None:
            continue

        wind_ms = round(wind_kmh / 3.6, 2) if wind_kmh is not None else None
        parts = []
        if temp_max is not None and temp_min is not None:
            parts.append(f"Temp: {temp_min}°C to {temp_max}°C")
        if wind_ms is not None:
            parts.append(f"Wind: {wind_ms} m/s max")
        if rain:
            parts.append(f"Rain: {rain} mm")
        elif rain is not None:
            parts.append("Dry")

        return {
            "temperature_max_c": temp_max,
            "temperature_min_c": temp_min,
            "wind_speed_max_ms": wind_ms,
            "rain_sum_mm": rain,
            "description": ", ".join(parts),
        }

    return unavailable
