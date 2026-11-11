"""
Writes synthetic DJI flight-record (.txt) files for the parser tests, following the
layout documented by dji-log-parser (MIT): a 100-byte prefix, records of
type / length / payload / 0xFF, and a details block. Versions 7-12 XOR every payload
with a key derived from CRC-64/Jones; 13+ add AES-256-CBC on top for most record types.
Standalone (no FlightMD imports) so it can't share a mistake with the decoder.
"""

import math
import struct

POLY_REFLECTED = 0x95AC9329AC4BC9B5
MASK64 = (1 << 64) - 1


def _table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ POLY_REFLECTED if c & 1 else c >> 1
        t.append(c)
    return t


TABLE = _table()


def crc64(crc, data):
    for b in data:
        crc = TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc


def xor_key(seed, rtype):
    return crc64((seed + rtype) & 0xFF, ((0x123456789ABCDEF0 * seed) & MASK64).to_bytes(8, "little")).to_bytes(8, "little")


def xor(data, key):
    return bytes(b ^ key[i % 8] for i, b in enumerate(data))


# record types
OSD, HOME, GIMBAL, RC, CUSTOM, DEFORM, CENTER_BATTERY, SMART_BATTERY = 1, 2, 3, 4, 5, 6, 7, 8
SMART_BATTERY_GROUP, KEY_STORAGE_RECOVER, KEY_STORAGE = 22, 50, 56

BASE_FEATURE = 1
AES_TYPES = {OSD: 1, HOME: 1, GIMBAL: 1, RC: 1, CENTER_BATTERY: 1, SMART_BATTERY: 1, DEFORM: 1, CUSTOM: 7, SMART_BATTERY_GROUP: 6}


def osd(lat_deg, lon_deg, height_m, vx=0.0, vy=0.0, vz=0.0, roll=0.0, pitch=0.0, yaw=0.0,
        flight_mode=6, on_ground=False, motors_on=True, gps_valid=True, sats=12, fly_time_s=0.0,
        battery=80, drone_type=58):
    bitpack1 = flight_mode & 0x7F
    bitpack2 = ((0 if on_ground else 2) << 1) | (0x08 if motors_on else 0)
    bitpack3 = 0x80 if gps_valid else 0
    return struct.pack(
        "<dd7h12BHBHBBB",
        math.radians(lon_deg), math.radians(lat_deg),
        round(height_m * 10), round(vx * 10), round(vy * 10), round(vz * 10),
        round(pitch * 10), round(roll * 10), round(yaw * 10),
        bitpack1, 0, bitpack2, bitpack3, 0, 0, sats, 0, 0, 0, battery, 0,
        round(fly_time_s * 10), 0, 0, 1, drone_type, 0,
    )


def home(lat_deg, lon_deg, alt_m):
    return struct.pack("<ddf", math.radians(lon_deg), math.radians(lat_deg), alt_m * 10) + bytes(16)


def center_battery(percent, volts, amps, cells, temp_c=None):
    cell_mv = [round(volts / cells * 1000)] * cells + [0] * (6 - cells)
    out = struct.pack("<BHHHBHIh6HHH", percent, round(volts * 1000), 2000, 3000, 90, 12, 0,
                      round(-amps * 1000), *cell_mv, 1, 1)
    if temp_c is not None:
        out += struct.pack("<H", round((temp_c + 273.15) * 10)) + bytes(6)
    return out


def battery_dynamic(index, volts, amps, percent, cells, temp_c=30.0, full=3000, remained=2000):
    return struct.pack("<BBiiIIhBBQ", 2, index, round(volts * 1000), round(-amps * 1000),
                       full, remained, round(temp_c * 10), cells, percent, 0)


def battery_static(index, designed_mah):
    return struct.pack("<BBIHIH", 1, index, designed_mah, 10, 17600, 0) + bytes(30)


def custom(epoch_ms, h_speed=0.0, distance=0.0):
    return struct.pack("<BBffq", 0, 0, h_speed, distance, epoch_ms)


def gimbal(pitch, roll, yaw):
    return struct.pack("<3h", round(pitch * 10), round(roll * 10), round(yaw * 10)) + bytes(6)


def rc(aileron=1024, elevator=1024, throttle=1024, rudder=1024):
    return struct.pack("<5H", aileron, elevator, throttle, rudder, 1024) + bytes(5)


def record(rtype, payload, version, seed=0x5A, aes=None):
    """aes: (key, iv) for a v13+ AES record; returns (bytes, next_iv)."""
    next_iv = None
    if version <= 6:
        content = payload
    elif aes is None:
        content = bytes([seed]) + xor(payload, xor_key(seed, rtype))
    else:
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key, iv = aes
        padder = padding.PKCS7(128).padder()
        padded = padder.update(payload) + padder.finalize()
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        ct = enc.update(padded) + enc.finalize()
        next_iv = ct[-16:]
        # the byte after the ciphertext isn't part of the content
        content = bytes([seed]) + xor(ct, xor_key(seed, rtype)) + b"\x00"
    if version <= 12:
        assert len(content) < 256
        head = bytes([rtype, len(content)])
    else:
        head = bytes([rtype]) + struct.pack("<H", len(content))
    return head + content + b"\xff", next_iv


def details(start_ms):
    d = bytearray(400)
    struct.pack_into("<q", d, 91, start_ms)
    d[280:280 + 8] = b"TestDrone"[:8]
    return bytes(d)


def build(records, version, start_ms=1_780_000_000_000, aux_version=1, department=3):
    """records: list of already-encoded record bytes."""
    body = b"".join(records)
    det = details(start_ms)
    if version < 12:
        rec_off = 100 if version >= 6 else 12
        prefix = struct.pack("<QHBB", rec_off + len(body), len(det), version, 0)
        prefix = prefix.ljust(rec_off, b"\x00")
        return prefix + body + det
    if version == 12:
        prefix = struct.pack("<QHBB", 0, len(det), version, 0).ljust(100, b"\x00")
        return prefix + det.ljust(436, b"\x00") + body
    info = bytes([1]) + struct.pack("<H", len(det)) + det + struct.pack("<H", 0)
    seed = 0x33
    aux_info = bytes([seed]) + xor(info, xor_key(seed, 0))
    aux = bytes([0]) + struct.pack("<H", len(aux_info)) + aux_info
    aux += bytes([1]) + struct.pack("<H", 3) + struct.pack("<HB", aux_version, department)
    rec_off = 100 + len(aux)
    prefix = struct.pack("<QHBB", rec_off, len(det), version, 0).ljust(100, b"\x00")
    return prefix + aux + body


def key_storage(feature_point, data, version):
    rec, _ = record(KEY_STORAGE, struct.pack("<HH", feature_point, len(data)) + data, version)
    return rec
