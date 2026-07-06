import json
import logging
import urllib.request
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)


def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """
    Resolve GPS coordinates to a human-readable place name via
    OpenStreetMap's Nominatim (free, no API key). Safe fallback: returns
    None on error, offline, or missing coordinates — never raises.
    """
    if not lat or not lon:
        return None

    params = urllib.parse.urlencode({
        "lat": f"{lat:.5f}",
        "lon": f"{lon:.5f}",
        "format": "jsonv2",
        "zoom": "10",  # city/town level — precise enough to be useful,
                       # coarse enough not to look like a street address
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
