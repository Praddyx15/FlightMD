import json
import logging
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """
    Place name for a coordinate via OpenStreetMap Nominatim (free, no key).
    Returns None on any failure; never raises.
    """
    # 0,0 is what an unset GPS reports
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return None

    params = urllib.parse.urlencode({
        "lat": f"{lat:.5f}",
        "lon": f"{lon:.5f}",
        "format": "jsonv2",
        "zoom": "10",  # town level, not a street address (people share these)
    })
    url = f"https://nominatim.openstreetmap.org/reverse?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FlightMD/1.0 (flight log analyser)"})
        with urllib.request.urlopen(req, timeout=2.0) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Reverse geocoding failed: {e}")
        return None

    address = data.get("address") or {}
    locality = (
        address.get("city") or address.get("town") or address.get("village")
        or address.get("county") or address.get("state")
    )
    country = address.get("country")

    if locality and country:
        return f"{locality}, {country}"
    return locality or country or data.get("display_name")
