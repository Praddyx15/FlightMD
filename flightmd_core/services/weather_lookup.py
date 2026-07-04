import logging
import json
import urllib.request
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

def fetch_weather(lat: float, lon: float, timestamp_utc: Optional[str]) -> dict:
    """
    Fetch historical or current weather from Open-Meteo API.
    Safe fallback: returns default dict on error or offline.
    """
    default_weather = {
        "temperature_max_c": None,
        "temperature_min_c": None,
        "wind_speed_max_ms": None,
        "rain_sum_mm": None,
        "description": "Weather data unavailable",
    }

    if not lat or not lon:
        return default_weather

    # Parse date from timestamp_utc (format: "YYYY-MM-DD HH:MM:SS" or similar)
    date_str = None
    if timestamp_utc:
        try:
            # Try parsing typical formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(timestamp_utc.split(".")[0], fmt)
                    date_str = dt.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"Failed to parse timestamp_utc {timestamp_utc}: {e}")

    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

    # Call Open-Meteo Archive API
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat:.4f}&longitude={lon:.4f}&start_date={date_str}&end_date={date_str}"
        f"&daily=temperature_2m_max,temperature_2m_min,wind_speed_10m_max,rain_sum"
        f"&timezone=auto"
    )

    try:
        logger.info(f"Fetching weather from: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "FlightMD/1.0"})
        with urllib.request.urlopen(req, timeout=2.0) as response:
            data = json.loads(response.read().decode("utf-8"))
            if "daily" in data:
                daily = data["daily"]
                temp_max = daily.get("temperature_2m_max", [None])[0]
                temp_min = daily.get("temperature_2m_min", [None])[0]
                wind_max_kmh = daily.get("wind_speed_10m_max", [None])[0]
                rain_sum = daily.get("rain_sum", [None])[0]

                # Convert wind from km/h to m/s
                wind_max_ms = round(wind_max_kmh / 3.6, 2) if wind_max_kmh is not None else None

                # Build description
                desc_parts = []
                if temp_max is not None and temp_min is not None:
                    desc_parts.append(f"Temp: {temp_min}°C to {temp_max}°C")
                if wind_max_ms is not None:
                    desc_parts.append(f"Wind: {wind_max_ms} m/s max")
                if rain_sum:
                    desc_parts.append(f"Rain: {rain_sum} mm")
                else:
                    desc_parts.append("Dry/Clear")

                return {
                    "temperature_max_c": temp_max,
                    "temperature_min_c": temp_min,
                    "wind_speed_max_ms": wind_max_ms,
                    "rain_sum_mm": rain_sum,
                    "description": ", ".join(desc_parts),
                }
    except Exception as e:
        logger.warning(f"Failed to fetch weather from Open-Meteo: {e}")
        # Try forecast endpoint as fallback in case archive is too new
        try:
            forecast_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat:.4f}&longitude={lon:.4f}&current_weather=true"
            )
            req = urllib.request.Request(forecast_url, headers={"User-Agent": "FlightMD/1.0"})
            with urllib.request.urlopen(req, timeout=2.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                if "current_weather" in data:
                    cw = data["current_weather"]
                    temp = cw.get("temperature")
                    wind_speed_kmh = cw.get("windspeed")
                    wind_speed_ms = round(wind_speed_kmh / 3.6, 2) if wind_speed_kmh is not None else None
                    return {
                        "temperature_max_c": temp,
                        "temperature_min_c": temp,
                        "wind_speed_max_ms": wind_speed_ms,
                        "rain_sum_mm": 0.0,
                        "description": f"Temp: {temp}°C, Wind: {wind_speed_ms} m/s (Current)",
                    }
        except Exception as e2:
            logger.warning(f"Failed fallback weather query: {e2}")

    return default_weather
