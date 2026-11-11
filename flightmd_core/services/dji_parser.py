"""
DJI flight record (.txt, the "DJIFlightRecord_*.txt" the DJI GO / Fly / Pilot apps write)
parser. The layout follows the description in dji-log-parser by Luc Vauvillier (MIT):

  prefix (100 bytes: detail offset, detail length, format version)
  records: type (1 byte), length (1 byte, 2 from v13), payload, 0xFF
  details: start time, totals, aircraft name...

Payloads are plain up to v6, XORed with a CRC-64 derived key from v7, and from v13 most
of them are also AES-256-CBC encrypted. The AES keys only come from DJI's keychain API,
which needs a DJI developer app key (DJI_API_KEY) and a network connection, so v13+ logs
need both; decryption also needs the optional `cryptography` package.

Records are 10 Hz OSD frames with the others in between, so every sample gets the time
of the OSD frame before it (frame index x 100 ms). Mapping onto PX4 topics:
  OSD             vehicle_gps_position, vehicle_local_position, vehicle_attitude,
                  vehicle_status (motors on = armed, flight mode), vehicle_land_detected
  battery records battery_status
  RC              manual_control_setpoint
  GIMBAL, DEFORM  dji_gimbal, dji_deform (no PX4 equivalent)

Aircraft-side .DAT files are a different format and aren't supported (see DAT_UNSUPPORTED).
"""

import base64
import json
import logging
import math
import os
import struct
import urllib.error
import urllib.request
from typing import Optional

import numpy as np
import pandas as pd

from flightmd_core.models.metadata import MIN_EPOCH_US, FlightMetadata, utc_iso
from flightmd_core.services.ardupilot_parser import store_instances

logger = logging.getLogger(__name__)

KEYCHAIN_URL = "https://dev.dji.com/openapi/v1/flight-records/keychains"
KEYCHAIN_TIMEOUT_S = 30
MAX_REPLY_BYTES = 4 * 1024 * 1024

PREFIX_SIZE = 100
OLD_PREFIX_SIZE = 12
V12_DETAILS_SIZE = 436
MAX_VERSION = 20
OSD_PERIOD_US = 100_000

DAT_UNSUPPORTED = (
    "This is a DJI aircraft .DAT log. FlightMD can't read .DAT files: recent aircraft "
    "encrypt them, and there's no openly licensed decoder for them. Upload the app's "
    "flight record instead (DJIFlightRecord_*.txt from the DJI Fly / GO / Pilot app)."
)

# record types
OSD, HOME, GIMBAL, RC, CUSTOM, DEFORM, CENTER_BATTERY, SMART_BATTERY = 1, 2, 3, 4, 5, 6, 7, 8
SMART_BATTERY_GROUP, KEY_STORAGE_RECOVER, KEY_STORAGE = 22, 50, 56
READ_TYPES = {OSD, HOME, GIMBAL, RC, CUSTOM, DEFORM, CENTER_BATTERY, SMART_BATTERY, SMART_BATTERY_GROUP}

FEATURE_NAMES = {
    1: "FR_Standardization_Feature_Base_1",
    2: "FR_Standardization_Feature_Vision_2",
    3: "FR_Standardization_Feature_Waypoint_3",
    4: "FR_Standardization_Feature_Agriculture_4",
    5: "FR_Standardization_Feature_AirLink_5",
    6: "FR_Standardization_Feature_AfterSales_6",
    7: "FR_Standardization_Feature_DJIFlyCustom_7",
    8: "FR_Standardization_Feature_Plaintext_8",
    9: "FR_Standardization_Feature_FlightHub_9",
    10: "FR_Standardization_Feature_Gimbal_10",
    11: "FR_Standardization_Feature_RC_11",
    12: "FR_Standardization_Feature_Camera_12",
    13: "FR_Standardization_Feature_Battery_13",
    14: "FR_Standardization_Feature_FlySafe_14",
    15: "FR_Standardization_Feature_Security_15",
}
FEATURE_IDS = {v: k for k, v in FEATURE_NAMES.items()}
BASE, VISION, WAYPOINT, AGRICULTURE, AIRLINK, AFTER_SALES, FLY_CUSTOM, PLAINTEXT = 1, 2, 3, 4, 5, 6, 7, 8
FLIGHT_HUB, GIMBAL_F, RC_F, CAMERA_F, BATTERY_F, FLY_SAFE, SECURITY = 9, 10, 11, 12, 13, 14, 15

# record type -> feature point (whose key decrypts it); v13 used Base for a few that
# got their own feature point in v14
_FEATURES = {
    1: BASE, 2: BASE, 5: FLY_CUSTOM, 6: BASE, 9: FLY_CUSTOM, 10: FLY_CUSTOM, 12: AFTER_SALES,
    13: BASE, 14: BASE, 15: BASE, 16: AFTER_SALES, 17: VISION, 18: VISION, 19: AFTER_SALES,
    20: FLY_CUSTOM, 21: AGRICULTURE, 24: FLY_CUSTOM, 26: AFTER_SALES, 27: AFTER_SALES,
    30: FLY_CUSTOM, 31: WAYPOINT, 32: WAYPOINT, 34: WAYPOINT, 35: WAYPOINT, 36: WAYPOINT,
    38: WAYPOINT, 39: WAYPOINT, 40: BASE, 41: AGRICULTURE, 43: AGRICULTURE, 44: AGRICULTURE,
    45: AGRICULTURE, 46: AGRICULTURE, 47: AGRICULTURE, 48: AGRICULTURE, 49: AIRLINK,
    50: PLAINTEXT, 54: FLY_CUSTOM, 55: SECURITY, 56: PLAINTEXT, 58: BASE, 59: BASE,
    62: RC_F, 63: BASE,
}
_FEATURES_V14 = {
    3: GIMBAL_F, 4: RC_F, 7: BATTERY_F, 8: BATTERY_F, 11: RC_F, 22: BATTERY_F, 25: CAMERA_F,
    28: FLY_SAFE, 29: RC_F, 33: RC_F, 51: FLY_SAFE, 52: FLY_SAFE, 53: FLIGHT_HUB,
}
_FEATURES_V13 = {
    3: BASE, 4: BASE, 7: BASE, 8: BASE, 11: BASE, 22: AFTER_SALES, 25: BASE, 28: AFTER_SALES,
    29: BASE, 33: BASE, 51: AFTER_SALES, 52: AFTER_SALES, 53: AFTER_SALES,
}

# OSD flight mode -> PX4 nav_state, where there is a sensible match
_NAV_STATE = {
    0: 0, 1: 1, 2: 1, 3: 1, 6: 2, 7: 2, 8: 2, 9: 21, 10: 17, 11: 17, 12: 18, 13: 18,
    14: 3, 15: 5, 17: 14, 25: 19, 31: 2, 32: 2, 33: 18, 36: 5, 37: 18, 38: 2, 43: 2,
}
_MODE_NAMES = {
    0: "Manual", 1: "Atti", 2: "Atti Course Lock", 3: "Atti Hover", 4: "Hover", 5: "GPS Brake",
    6: "P-GPS", 7: "GPS Course Lock", 8: "GPS Home Lock", 9: "Point of Interest",
    10: "Assisted Takeoff", 11: "Auto Takeoff", 12: "Auto Landing", 13: "Atti Landing",
    14: "Waypoint", 15: "Go Home", 16: "Click Go", 17: "Virtual Stick", 19: "Cinematic",
    23: "Atti Limited", 24: "Draw", 25: "Follow Me", 26: "ActiveTrack", 27: "TapFly",
    28: "Pano", 30: "FPV", 31: "Sport", 32: "Novice", 33: "Confirm Landing",
    35: "Terrain Tracking", 36: "Advanced Go Home", 37: "Precision Landing", 38: "Tripod",
    39: "Track Headlock", 41: "Engine Start", 43: "Gentle",
}
_DRONE_TYPES = {
    1: "Inspire 1", 2: "Phantom 3 Advanced", 3: "Phantom 3 Pro", 4: "Phantom 3 Standard",
    11: "Phantom 4", 14: "Matrice 600", 15: "Phantom 3 4K", 16: "Mavic Pro", 17: "Inspire 2",
    18: "Phantom 4 Pro", 21: "Spark", 23: "Matrice 600 Pro", 24: "Mavic Air", 25: "Matrice 200",
    27: "Phantom 4 Advanced", 28: "Matrice 210", 29: "Phantom 3 SE", 30: "Matrice 210 RTK",
    36: "Phantom 4 Pro V2", 41: "Mavic 2", 51: "Mavic 2 Enterprise", 58: "Mavic Air 2",
    60: "Matrice 300 RTK", 63: "Mini 2", 77: "Mavic 3 Enterprise", 84: "Mavic 3 Pro",
    89: "Matrice 350 RTK", 93: "Mini 4 Pro", 94: "Avata 2",
}

RC_CENTRE, RC_SPAN = 1024, 660
EARTH_R_M = 6371000.0

POLY_REFLECTED = 0x95AC9329AC4BC9B5  # CRC-64/Jones, reflected
MASK64 = (1 << 64) - 1


def _crc_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ POLY_REFLECTED if c & 1 else c >> 1
        table.append(c)
    return table


_CRC_TABLE = _crc_table()


def crc64(crc: int, data: bytes) -> int:
    for b in data:
        crc = _CRC_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc


def xor_key(seed: int, record_type: int) -> bytes:
    k = crc64((seed + record_type) & 0xFF, ((0x123456789ABCDEF0 * seed) & MASK64).to_bytes(8, "little"))
    return k.to_bytes(8, "little")


def xor_decode(data: bytes, key: bytes) -> bytes:
    # 8-byte key repeated over the payload; numpy keeps this fast on 20 MB logs
    a = np.frombuffer(data, dtype=np.uint8)
    k = np.resize(np.frombuffer(key, dtype=np.uint8), len(a))
    return (a ^ k).tobytes()


def looks_like_dji_dat(header: bytes) -> bool:
    # "BUILD" at 16 = DatCon's check for a plain .DAT; "LOGH" starts the encrypted kind
    return header[16:21] == b"BUILD" or header[:4] == b"LOGH"


def _u16(b, pos):
    return b[pos] | (b[pos + 1] << 8)


def _layout(buf: bytes):
    """(version, detail_offset, aux_end) from the prefix; aux_end is where v13+ aux blocks
    stop (0 below v13). Raises IndexError when buf is too short to tell."""
    version = buf[10]
    detail_offset = int.from_bytes(buf[0:8], "little")
    aux_end = 0
    if version >= 13:
        if buf[PREFIX_SIZE] != 0:
            raise ValueError("no auxiliary info block")
        p = PREFIX_SIZE + 3 + _u16(buf, PREFIX_SIZE + 1)
        if buf[p] != 1:
            raise ValueError("no auxiliary version block")
        aux_end = p + 3 + _u16(buf, p + 1)
    return version, detail_offset, aux_end


def _records_range(version, detail_offset, aux_end, size):
    if version < 6:
        return OLD_PREFIX_SIZE, detail_offset
    if version < 12:
        return PREFIX_SIZE, detail_offset
    if version == 12:
        return PREFIX_SIZE + V12_DETAILS_SIZE, size
    return (detail_offset or aux_end), size


def check_dji_txt(buf: bytes, complete: bool = False) -> Optional[bool]:
    """True if buf starts like a DJI flight record, False if it doesn't, None if buf is
    too short to tell (and complete is False)."""
    if len(buf) <= 10:
        return False if complete else None
    if not 1 <= buf[10] <= MAX_VERSION:
        return False
    try:
        version, detail_offset, aux_end = _layout(buf)
    except IndexError:
        return False if complete else None
    except ValueError:
        return False
    start, end = _records_range(version, detail_offset, aux_end, len(buf) if complete else 1 << 62)
    if version < 12 and detail_offset < start:
        return False
    hdr = 2 if version <= 12 else 3
    pos, seen = start, 0
    while seen < 3:
        if pos >= end:
            return seen > 0
        if pos + hdr > len(buf):
            return False if complete else None
        n = buf[pos + 1] if hdr == 2 else _u16(buf, pos + 1)
        stop = pos + hdr + n
        if stop >= len(buf):
            return False if complete else None
        if buf[pos] in (0, 0xFF) or buf[stop] != 0xFF:
            return False
        pos = stop + 1
        seen += 1
    return True


def _iter_records(data: bytes, start: int, end: int, version: int, stats: dict):
    """Yields (type, content) with content still encoded. Skips embedded JPEGs and
    resyncs on the next 0xFF after a damaged record."""
    hdr = 2 if version <= 12 else 3
    pos = start
    while pos + hdr <= end:
        if data[pos] == 0xFF and data[pos + 1] == 0xD8:
            stop = data.find(b"\xff\xd9", pos + 2, end)
            pos = end if stop < 0 else stop + 2
            continue
        rtype = data[pos]
        n = data[pos + 1] if hdr == 2 else _u16(data, pos + 1)
        stop = pos + hdr + n
        if stop >= end or data[stop] != 0xFF:
            stats["damaged"] += 1
            nxt = data.find(b"\xff", pos + 1, end)
            pos = end if nxt < 0 else nxt + 1
            continue
        yield rtype, data[pos + hdr:stop]
        pos = stop + 1


def _feature(rtype: int, version: int) -> int:
    if rtype in _FEATURES:
        return _FEATURES[rtype]
    table = _FEATURES_V13 if version == 13 else _FEATURES_V14
    return table.get(rtype, PLAINTEXT)


def _aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> Optional[bytes]:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        raise ValueError(
            "Decrypting DJI v13+ logs needs the 'cryptography' package (pip install cryptography)."
        ) from None
    if len(key) not in (16, 24, 32) or len(iv) != 16 or not ct or len(ct) % 16:
        return None
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    pt = dec.update(ct) + dec.finalize()
    pad = pt[-1]
    if not 1 <= pad <= 16 or pt[-pad:] != bytes([pad]) * pad:
        return None
    return pt[:-pad]


def _payload(rtype: int, content: bytes, version: int, keychain: Optional[dict],
             decrypt: bool = True) -> Optional[bytes]:
    """The record's plain payload, or None. decrypt=False only moves the AES IV chain on,
    for v13+ records nobody reads: skipping them would break every later record of the
    same feature."""
    if version <= 6:
        return content
    if len(content) < 2:
        return None
    key = xor_key(content[0], rtype)
    if version <= 12:
        return xor_decode(content[1:], key)
    fp = _feature(rtype, version)
    if fp == PLAINTEXT:
        return xor_decode(content[1:], key)
    if not keychain or fp not in keychain:
        return None
    # the last content byte isn't part of the ciphertext
    ct = xor_decode(content[1:-1], key)
    if len(ct) < 16:
        return None
    iv, aes_key = keychain[fp]
    keychain[fp] = (ct[-16:], aes_key)  # CBC chains across records of the same feature
    if not decrypt:
        return None
    return _aes_cbc_decrypt(aes_key, iv, ct)


def _offline() -> bool:
    return os.environ.get("FLIGHTMD_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # a redirect would resend the Api-Key header to wherever it points
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_keychains(request_body: dict, api_key: str) -> list[dict[int, tuple[bytes, bytes]]]:
    """POSTs the KeyStorage ciphertexts to DJI and returns one {feature: (iv, key)} per
    keychain group."""
    req = urllib.request.Request(
        KEYCHAIN_URL,
        data=json.dumps(request_body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Api-Key": api_key},
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=KEYCHAIN_TIMEOUT_S) as resp:
            reply = json.loads(resp.read(MAX_REPLY_BYTES))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise ValueError("DJI's keychain service rejected the key in DJI_API_KEY (HTTP 403).") from None
        raise ValueError(f"DJI's keychain service answered HTTP {e.code}.") from None
    except (urllib.error.URLError, OSError) as e:
        raise ValueError(f"Couldn't reach DJI's keychain service: {getattr(e, 'reason', e)}") from None
    except json.JSONDecodeError:
        raise ValueError("DJI's keychain service sent a reply that isn't JSON.") from None

    result = (reply.get("result") or {}) if isinstance(reply, dict) else {}
    if result.get("code") != 0:
        raise ValueError(f"DJI's keychain service refused the request: {result.get('msg') or 'no reason given'}")
    chains = []
    for group in reply.get("data") or []:
        chain = {}
        for entry in group or []:
            fp = FEATURE_IDS.get(entry.get("featurePoint"))
            if fp is None:
                continue
            try:
                chain[fp] = (base64.b64decode(entry["aesIv"]), base64.b64decode(entry["aesKey"]))
            except (KeyError, ValueError, TypeError):
                continue
        chains.append(chain)
    return chains


def _keychain_request(data: bytes, start: int, end: int, version: int, aux: tuple[int, int]) -> dict:
    groups: list[list[dict]] = [[]]
    for rtype, content in _iter_records(data, start, end, version, {"damaged": 0}):
        if rtype == KEY_STORAGE:
            p = _payload(rtype, content, version, None)
            if p is None or len(p) < 4:
                continue
            fp, n = struct.unpack_from("<HH", p)
            if fp in FEATURE_NAMES:
                groups[-1].append({
                    "featurePoint": FEATURE_NAMES[fp],
                    "aesCiphertext": base64.b64encode(p[4:4 + n]).decode("ascii"),
                })
        elif rtype == KEY_STORAGE_RECOVER:
            groups.append([])
    aux_version, department = aux
    # unknown departments go out as DJI Fly, like the reference decoder does
    return {"version": aux_version, "department": department if 1 <= department <= 8 else 3,
            "keychainsArray": groups}


class DJIParser:
    """Same interface as ULogParser: .parse(path) -> (topics, params, metadata)."""

    def parse(self, path: str) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"DJI log file not found: {path}")
        with open(path, "rb") as f:
            data = f.read()
        if looks_like_dji_dat(data[:32]):
            raise ValueError(DAT_UNSUPPORTED)
        if len(data) < PREFIX_SIZE:
            raise ValueError("DJI flight record is too short to have a header.")

        logger.info(f"Parsing DJI flight record: {path}")
        try:
            version, detail_offset, aux_end = _layout(data)
        except (IndexError, ValueError) as e:
            raise ValueError(f"DJI flight record header is damaged ({e}).") from None
        start, end = _records_range(version, detail_offset, aux_end, len(data))
        if not start <= end <= len(data):
            raise ValueError("DJI flight record is truncated (records run past the end of the file).")

        start_us = self._start_time(data, version, detail_offset)
        keychains = None
        if version >= 13:
            api_key = os.environ.get("DJI_API_KEY", "").strip()
            if not api_key or _offline():
                raise ValueError(
                    f"DJI log v13+ needs DJI_API_KEY (a DJI developer app key) and network access "
                    f"to fetch its decryption keys; this one is v{version}. Set DJI_API_KEY and "
                    f"make sure FLIGHTMD_OFFLINE isn't 1."
                )
            p = PREFIX_SIZE + 3 + _u16(data, PREFIX_SIZE + 1)
            aux = struct.unpack_from("<HB", data, p + 3)
            keychains = fetch_keychains(_keychain_request(data, start, end, version, aux), api_key)

        frames = self._decode(data, start, end, version, keychains)
        if not frames["osd"]:
            raise ValueError("The DJI flight record has no readable OSD (flight) records.")
        topics = self._topics(frames)

        warnings = []
        if frames["damaged"]:
            warnings.append(f"{frames['damaged']} damaged records were skipped.")
        if frames["undecrypted"]:
            warnings.append(f"{frames['undecrypted']} records couldn't be decrypted and were skipped.")

        osd = frames["osd"]
        status = topics.get("vehicle_status")
        arm_count = 0
        if status is not None:
            armed = (status["arming_state"] == 2).to_numpy(dtype=int)
            arm_count = int(armed[0] + (np.diff(armed) == 1).sum())
        modes = sorted({_MODE_NAMES.get(r["mode"], f"Mode {r['mode']}") for r in osd})
        heights = [r["height"] for r in osd]
        speeds = [math.hypot(r["vx"], r["vy"]) for r in osd]
        drone = next((r["drone_type"] for r in osd if r["drone_type"]), None)

        start_utc = None
        if start_us and start_us >= MIN_EPOCH_US:
            start_utc = utc_iso(start_us)
        elif frames["custom_ms"]:
            # CUSTOM timestamps are wall-clock ms; take the first one back to frame 0
            k, ms = frames["custom_ms"][0]
            start_utc = utc_iso(ms * 1000 - k * OSD_PERIOD_US)

        metadata = FlightMetadata(
            duration_seconds=round((len(osd) - 1) * OSD_PERIOD_US / 1e6, 2),
            firmware_version=None,
            vehicle_type="Copter",
            airframe_name=_DRONE_TYPES.get(drone) if drone else None,
            log_start_utc=start_utc,
            arm_count=arm_count,
            flight_modes_used=modes,
            max_altitude_m=round(max(heights), 1),
            max_speed_ms=round(max(speeds), 2),
            available_topics=sorted(topics.keys()),
            parse_warnings=warnings,
        )
        logger.info(f"Parsed DJI v{version} log: {len(osd)} OSD frames, {len(topics)} topics")
        return topics, {}, metadata

    def _start_time(self, data, version, detail_offset) -> Optional[float]:
        """Flight start time in epoch us from the details block, or None."""
        if version < 12:
            block = data[detail_offset:]
        elif version == 12:
            block = data[PREFIX_SIZE:PREFIX_SIZE + V12_DETAILS_SIZE]
        else:
            n = _u16(data, PREFIX_SIZE + 1)
            content = data[PREFIX_SIZE + 3:PREFIX_SIZE + 3 + n]
            if len(content) < 4:
                return None
            info = xor_decode(content[1:], xor_key(content[0], 0))
            block = info[3:3 + _u16(info, 1)]
        if len(block) < 99:
            return None
        ms = struct.unpack_from("<q", block, 91)[0]
        return ms * 1000.0 if ms > 0 else None

    def _decode(self, data, start, end, version, keychains):
        stats = {"damaged": 0}
        chains = list(keychains or [])
        keychain = chains.pop(0) if chains else None
        osd, home, bat_dyn, bat_center, bat_smart, rc, gimbal, deform = [], [], [], [], [], [], [], []
        designed = {}
        custom_ms = []
        undecrypted = 0
        k = -1  # index of the last OSD frame

        for rtype, content in _iter_records(data, start, end, version, stats):
            if rtype == KEY_STORAGE_RECOVER:
                keychain = chains.pop(0) if chains else None
                continue
            # todo: FIRMWARE records (type 15) would give the aircraft firmware version
            if rtype not in READ_TYPES:
                if version >= 13:
                    _payload(rtype, content, version, keychain, decrypt=False)
                continue
            p = _payload(rtype, content, version, keychain)
            if p is None:
                undecrypted += 1
                continue
            t = max(k, 0)

            if rtype == OSD and len(p) >= 48:
                (lon, lat, height, vx, vy, vz, pitch, roll, yaw, bp1, _, bp2, bp3, _, _,
                 sats, *_rest) = struct.unpack_from("<dd7h12BHBHB", p)
                k += 1
                osd.append({
                    "k": k, "lat": math.degrees(lat), "lon": math.degrees(lon), "height": height / 10.0,
                    "vx": vx / 10.0, "vy": vy / 10.0, "vz": vz / 10.0,
                    "roll": roll / 10.0, "pitch": pitch / 10.0, "yaw": yaw / 10.0,
                    "mode": bp1 & 0x7F, "ground": (bp2 >> 1) & 0x03, "motors": bool(bp2 & 0x08),
                    "gps_ok": bool(bp3 & 0x80), "sats": sats,
                    "drone_type": p[48] if version >= 2 and len(p) > 48 else 0,
                })
            elif rtype == HOME and len(p) >= 20:
                lon, lat, alt = struct.unpack_from("<ddf", p)
                home.append((t, math.degrees(lat), math.degrees(lon), alt / 10.0))
            elif rtype == CENTER_BATTERY and len(p) >= 32:
                f = struct.unpack_from("<BHHHBHIh6H", p)
                cells = sum(1 for c in f[8:14] if c > 0)
                temp = struct.unpack_from("<H", p, 32)[0] / 10.0 - 273.15 if version >= 8 and len(p) >= 34 else np.nan
                bat_center.append((t, f[1] / 1000.0, abs(f[7]) / 1000.0, f[0] / 100.0, temp, cells or np.nan))
            elif rtype == SMART_BATTERY and len(p) >= 27:
                f = struct.unpack_from("<5HffIBBHB", p)
                bat_smart.append((t, f[10] / 1000.0, f[11] / 100.0))
            elif rtype == SMART_BATTERY_GROUP and len(p) >= 2:
                if p[0] == 2 and len(p) >= 30:
                    idx, mv, ma, _full, _left, temp, cells, pct, _ = struct.unpack_from("<BiiIIhBBQ", p, 1)
                    # current is negative while discharging
                    bat_dyn.append((idx, t, mv / 1000.0, abs(ma) / 1000.0, pct / 100.0, temp / 10.0, cells))
                elif p[0] == 1 and len(p) >= 6:
                    idx, cap = struct.unpack_from("<BI", p, 1)
                    designed[idx] = cap
            elif rtype == CUSTOM and len(p) >= 18:
                ms = struct.unpack_from("<q", p, 10)[0]
                if ms * 1000 >= MIN_EPOCH_US:
                    custom_ms.append((t, ms))
            elif rtype == RC and len(p) >= 8:
                a, e, thr, r = struct.unpack_from("<4H", p)
                rc.append((t, (a - RC_CENTRE) / RC_SPAN, (e - RC_CENTRE) / RC_SPAN,
                           (r - RC_CENTRE) / RC_SPAN, (thr - RC_CENTRE) / RC_SPAN))
            elif rtype == GIMBAL and len(p) >= 6:
                gp, gr, gy = struct.unpack_from("<3h", p)
                gimbal.append((t, gr / 10.0, gp / 10.0, gy / 10.0))
            elif rtype == DEFORM and len(p) >= 1:
                deform.append((t, bool(p[0] & 0x01), (p[0] & 0x0E) >> 1, (p[0] & 0x30) >> 4))

        return {
            "osd": osd, "home": home, "bat_dyn": bat_dyn, "bat_center": bat_center,
            "bat_smart": bat_smart, "designed": designed, "custom_ms": custom_ms, "rc": rc,
            "gimbal": gimbal, "deform": deform, "damaged": stats["damaged"],
            "undecrypted": undecrypted,
        }

    def _topics(self, fr) -> dict[str, pd.DataFrame]:
        topics: dict[str, pd.DataFrame] = {}
        o = pd.DataFrame(fr["osd"])
        # NaN or out-of-range coordinates only come from a record that decoded to junk
        o = o[(o["lat"].abs() <= 90) & (o["lon"].abs() <= 180)].reset_index(drop=True)
        ts = o["k"].to_numpy(dtype=np.int64) * OSD_PERIOD_US
        valid = o["gps_ok"] & ((o["lat"] != 0) | (o["lon"] != 0))

        # OSD height is above the take-off point; the home record has the absolute altitude
        home = fr["home"]
        home_alt = home[0][3] if home else 0.0
        if home:
            ref_lat, ref_lon = home[0][1], home[0][2]
        elif valid.any():
            ref_lat, ref_lon = o.loc[valid.idxmax(), ["lat", "lon"]]
        else:
            ref_lat = ref_lon = None

        topics["vehicle_gps_position"] = pd.DataFrame({
            "timestamp": ts,
            "lat": (o["lat"] * 1e7).round().astype("int64"),
            "lon": (o["lon"] * 1e7).round().astype("int64"),
            "alt": ((o["height"] + home_alt) * 1000.0).round().astype("int64"),
            "fix_type": np.where(valid, 3, 0).astype("int64"),
            "satellites_used": o["sats"].astype("int64"),
            "vel_m_s": np.hypot(o["vx"], o["vy"]),
        })

        local = pd.DataFrame({"timestamp": ts, "x": np.nan, "y": np.nan, "z": -o["height"],
                              "vx": o["vx"], "vy": o["vy"], "vz": o["vz"]})
        if ref_lat is not None:
            x = np.radians(o["lat"] - ref_lat) * EARTH_R_M
            y = np.radians(o["lon"] - ref_lon) * EARTH_R_M * math.cos(math.radians(ref_lat))
            local["x"] = np.where(valid, x, np.nan)
            local["y"] = np.where(valid, y, np.nan)
        topics["vehicle_local_position"] = local

        roll, pitch, yaw = (np.radians(o[c].to_numpy(float)) for c in ("roll", "pitch", "yaw"))
        att = pd.DataFrame({"timestamp": ts, "roll": roll, "pitch": pitch, "yaw": yaw})
        cr, sr = np.cos(roll / 2), np.sin(roll / 2)
        cp, sp = np.cos(pitch / 2), np.sin(pitch / 2)
        cy, sy = np.cos(yaw / 2), np.sin(yaw / 2)
        att["q[0]"] = cr * cp * cy + sr * sp * sy
        att["q[1]"] = sr * cp * cy - cr * sp * sy
        att["q[2]"] = cr * sp * cy + sr * cp * sy
        att["q[3]"] = cr * cp * sy - sr * sp * cy
        topics["vehicle_attitude"] = att

        nav = o["mode"].map(_NAV_STATE).astype(float)
        status = pd.DataFrame({"timestamp": ts, "arming_state": np.where(o["motors"], 2, 1), "nav_state": nav})
        cmp = status[["arming_state", "nav_state"]].fillna(-1)
        topics["vehicle_status"] = status[cmp.ne(cmp.shift()).any(axis=1)].reset_index(drop=True)

        # ground_or_sky: 0/1 on the ground, 2/3 in the air
        land = pd.DataFrame({"timestamp": ts, "landed": o["ground"] <= 1})
        land = land[land["landed"].ne(land["landed"].shift())]
        if not land.empty:
            topics["vehicle_land_detected"] = land.reset_index(drop=True)

        bat = self._battery(fr)
        if bat:
            store_instances(topics, "battery_status", bat)

        if fr["rc"]:
            df = pd.DataFrame(fr["rc"], columns=["timestamp", "roll", "pitch", "yaw", "throttle"])
            df["timestamp"] *= OSD_PERIOD_US
            topics["manual_control_setpoint"] = df
        if fr["gimbal"]:
            df = pd.DataFrame(fr["gimbal"], columns=["timestamp", "roll_deg", "pitch_deg", "yaw_deg"])
            df["timestamp"] *= OSD_PERIOD_US
            topics["dji_gimbal"] = df
        if fr["deform"]:
            df = pd.DataFrame(fr["deform"], columns=["timestamp", "protected", "deform_status", "deform_mode"])
            df["timestamp"] *= OSD_PERIOD_US
            topics["dji_deform"] = df
        return topics

    def _battery(self, fr) -> dict[int, pd.DataFrame]:
        """Smart battery group records (current, temperature, cells) when the aircraft
        sends them, else the centre battery, else the older smart battery record."""
        cols = ["timestamp", "voltage_v", "current_a", "remaining", "temperature", "cell_count"]
        out = {}
        if fr["bat_dyn"]:
            per: dict[int, list] = {}
            for idx, *row in fr["bat_dyn"]:
                per.setdefault(idx, []).append(row)
            for idx, rows in per.items():
                df = pd.DataFrame(rows, columns=cols)
                if fr["designed"].get(idx, 0) > 0:
                    df["capacity"] = float(fr["designed"][idx])
                out[idx] = df
        elif fr["bat_center"]:
            out[0] = pd.DataFrame(fr["bat_center"], columns=cols)
        elif fr["bat_smart"]:
            out[0] = pd.DataFrame(fr["bat_smart"], columns=["timestamp", "voltage_v", "remaining"])
        for df in out.values():
            df["timestamp"] = df["timestamp"].astype("int64") * OSD_PERIOD_US
        return out
