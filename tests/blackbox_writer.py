"""
Writes small synthetic Betaflight blackbox logs for the parser tests.

Encoders follow the documented blackbox format (Cleanflight "Blackbox logging internals"
plus the Betaflight additions: MINMOTOR predictor, TAG2_3SVARIABLE). Standalone on
purpose: it has no FlightMD imports, so it can't share a mistake with the decoder.
"""

import struct

MARKER = b"H Product:Blackbox flight data recorder by Nicholas Sherlock\n"

# predictors
P_ZERO, P_PREV, P_LINE, P_AVG2, P_MINTHR, P_MOTOR0, P_INC, P_HOME, P_1500, P_VBATREF, P_LASTTIME, P_MINMOTOR = range(12)
# encodings
E_SVB, E_UVB, E_NEG14, E_TAG8_8SVB, E_TAG2_3S32, E_TAG8_4S16, E_NULL, E_TAG2_3SVAR = 0, 1, 3, 6, 7, 8, 9, 10


def uvb(v):
    v &= 0xFFFFFFFF
    out = bytearray()
    while v > 127:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)
    return bytes(out)


def zigzag(v):
    return ((v << 1) ^ (v >> 31)) & 0xFFFFFFFF


def svb(v):
    return uvb(zigzag(v))


def neg14(v):
    return uvb(-v & 0x3FFF)


def tag8_8svb(values):
    if len(values) == 1:
        return svb(values[0])
    head = 0
    body = b""
    for i, v in enumerate(values):
        if v:
            head |= 1 << i
            body += svb(v)
    return bytes([head]) + body


def _fits(v, bits):
    return -(1 << (bits - 1)) <= v < (1 << (bits - 1))


def tag2_3s32(values):
    a, b, c = values
    if all(_fits(v, 2) for v in values):
        return bytes([((a & 3) << 4) | ((b & 3) << 2) | (c & 3)])
    if all(_fits(v, 4) for v in values):
        return bytes([0x40 | (a & 0xF), ((b & 0xF) << 4) | (c & 0xF)])
    if all(_fits(v, 6) for v in values):
        return bytes([0x80 | (a & 0x3F), b & 0x3F, c & 0x3F])
    sel = 0
    body = b""
    for i, v in enumerate(values):
        for k, bits in enumerate((8, 16, 24, 32)):
            if _fits(v, bits):
                break
        sel |= k << (2 * i)
        body += (v & 0xFFFFFFFF).to_bytes(4, "little")[:k + 1]
    return bytes([0xC0 | sel]) + body


def tag2_3svariable(values):
    a, b, c = values
    if all(_fits(v, 2) for v in values):
        return bytes([((a & 3) << 4) | ((b & 3) << 2) | (c & 3)])
    if _fits(a, 5) and _fits(b, 5) and _fits(c, 4):
        return bytes([0x40 | ((a & 0x1F) << 1) | ((b & 0x1F) >> 4), ((b & 0xF) << 4) | (c & 0xF)])
    if _fits(a, 8) and _fits(b, 7) and _fits(c, 7):
        return bytes([0x80 | ((a & 0xFF) >> 2), ((a & 3) << 6) | ((b & 0x7F) >> 1), ((b & 1) << 7) | (c & 0x7F)])
    return tag2_3s32(values)


def tag8_4s16(values):
    # v2 layout: a bit stream, most significant nibble first
    head = 0
    nibbles = []
    for i, v in enumerate(values):
        if v == 0:
            sel, n = 0, 0
        elif _fits(v, 4):
            sel, n = 1, 1
        elif _fits(v, 8):
            sel, n = 2, 2
        else:
            sel, n = 3, 4
        head |= sel << (2 * i)
        for k in reversed(range(n)):
            nibbles.append((v >> (4 * k)) & 0xF)
    if len(nibbles) % 2:
        nibbles.append(0)
    body = bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))
    return bytes([head]) + body


GROUPED = {E_TAG2_3S32: (3, tag2_3s32), E_TAG2_3SVAR: (3, tag2_3svariable), E_TAG8_4S16: (4, tag8_4s16)}

# name, signed, I predictor, I encoding, P predictor, P encoding
DEFAULT_FIELDS = [
    ("loopIteration", 0, P_ZERO, E_UVB, P_INC, E_NULL),
    ("time", 0, P_ZERO, E_UVB, P_LINE, E_SVB),
    *[(f"axisI[{i}]", 1, P_ZERO, E_SVB, P_PREV, E_TAG2_3S32) for i in range(3)],
    *[(f"rcCommand[{i}]", 1, P_ZERO, E_SVB, P_PREV, E_TAG8_4S16) for i in range(4)],
    *[(f"setpoint[{i}]", 1, P_ZERO, E_SVB, P_PREV, E_TAG8_4S16) for i in range(4)],
    ("vbatLatest", 0, P_VBATREF, E_NEG14, P_PREV, E_TAG8_8SVB),
    ("amperageLatest", 1, P_ZERO, E_SVB, P_PREV, E_TAG8_8SVB),
    *[(f"magADC[{i}]", 1, P_ZERO, E_SVB, P_PREV, E_TAG2_3SVAR) for i in range(3)],
    *[(f"gyroADC[{i}]", 1, P_ZERO, E_SVB, P_AVG2, E_SVB) for i in range(3)],
    *[(f"accSmooth[{i}]", 1, P_ZERO, E_SVB, P_AVG2, E_SVB) for i in range(3)],
    ("motor[0]", 0, P_MINMOTOR, E_UVB, P_AVG2, E_SVB),
    *[(f"motor[{i}]", 0, P_MOTOR0, E_SVB, P_AVG2, E_SVB) for i in range(1, 4)],
    *[(f"eRPM[{i}]", 0, P_ZERO, E_UVB, P_PREV, E_SVB) for i in range(4)],
]

SLOW_FIELDS = ["flightModeFlags", "stateFlags", "failsafePhase", "rxSignalReceived", "rxFlightChannelsValid"]
GPS_FIELDS = [
    # name, signed, predictor, encoding
    ("time", 0, P_LASTTIME, E_UVB),
    ("GPS_numSat", 0, P_ZERO, E_UVB),
    ("GPS_coord[0]", 1, P_HOME, E_SVB),
    ("GPS_coord[1]", 1, P_HOME, E_SVB),
    ("GPS_altitude", 1, P_ZERO, E_SVB),
    ("GPS_speed", 0, P_ZERO, E_UVB),
    ("GPS_ground_course", 0, P_ZERO, E_UVB),
]

DEFAULT_HEADERS = {
    "Data version": "2",
    "Firmware type": "Betaflight",
    "Firmware revision": "Betaflight 4.4.2 (4b26d4ac0) STM32F7X2",
    "Board information": "TEST FAKEBOARD",
    "Log start datetime": "2026-05-01T10:15:30.000+00:00",
    "minthrottle": "1070",
    "motorOutput": "158,2047",
    "vbatref": "1650",
    "acc_1G": "2048",
    "gyro_scale": "0x3f800000",
    "motor_poles": "14",
    "debug_mode": "0",
    "rollPID": "45,80,40",
    "pitchPID": "47,84,46",
    "yawPID": "45,80,0",
}


class BlackboxWriter:
    """Builds one log session. Main frames are fed every loop iteration; the writer
    only emits the ones the I/P interval says get logged, like the firmware does."""

    def __init__(self, fields=DEFAULT_FIELDS, headers=None, i_interval=32, p_denom=1, gps=True):
        self.fields = fields
        self.names = [f[0] for f in fields]
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.i_interval = i_interval
        self.p_denom = p_denom
        self.gps = gps
        self.minmotor = int(self.headers["motorOutput"].split(",")[0])
        self.minthrottle = int(self.headers["minthrottle"])
        self.vbatref = int(self.headers["vbatref"])
        self.prev = self.prev2 = None
        self.last_time = 0
        self.home = (0, 0)
        self.out = bytearray()

    def header(self):
        h = dict(self.headers)
        h["I interval"] = str(self.i_interval)
        h["P interval"] = str(self.p_denom)
        lines = [MARKER]
        defs = {
            "I": (self.names, [f[1] for f in self.fields], [f[2] for f in self.fields], [f[3] for f in self.fields]),
        }
        lines += _field_lines("I", *defs["I"])
        lines.append(_hline("Field P predictor", ",".join(str(f[4]) for f in self.fields)))
        lines.append(_hline("Field P encoding", ",".join(str(f[5]) for f in self.fields)))
        lines += _field_lines("S", SLOW_FIELDS, [0] * 5, [0] * 5, [E_UVB] * 5)
        if self.gps:
            lines += _field_lines("H", ["GPS_home[0]", "GPS_home[1]"], [1, 1], [0, 0], [E_SVB, E_SVB])
            lines += _field_lines("G", [g[0] for g in GPS_FIELDS], [g[1] for g in GPS_FIELDS],
                                  [g[2] for g in GPS_FIELDS], [g[3] for g in GPS_FIELDS])
        for k, v in h.items():
            lines.append(_hline(k, v))
        self.out += b"".join(lines)
        return self

    def logged(self, iteration):
        return iteration % self.i_interval == 0 or (iteration % self.i_interval) % self.p_denom == 0

    def main(self, iteration, values):
        """values: name -> int for every field except loopIteration."""
        if not self.logged(iteration):
            return self
        cur = [iteration if n == "loopIteration" else int(values[n]) for n in self.names]
        intra = iteration % self.i_interval == 0 or self.prev is None
        col = 2 if intra else 4
        preds = []
        for i, f in enumerate(self.fields):
            p = f[col]
            preds.append(self._predict(p, i, cur))
        # the firmware subtracts in int32, so a time rollover stays a small residual
        resid = [((c - p + 0x80000000) & 0xFFFFFFFF) - 0x80000000 for c, p in zip(cur, preds)]
        encs = [f[3 if intra else 5] for f in self.fields]
        pr = [f[col] for f in self.fields]
        self.out += b"I" if intra else b"P"
        self.out += _encode(resid, encs, pr)
        if intra:
            self.prev = self.prev2 = cur
        else:
            self.prev2, self.prev = self.prev, cur
        self.last_time = cur[self.names.index("time")]
        return self

    def _predict(self, p, i, cur):
        prev, prev2 = self.prev, self.prev2
        if p == P_ZERO:
            return 0
        if p == P_PREV:
            return prev[i]
        if p == P_LINE:
            return 2 * prev[i] - prev2[i]
        if p == P_AVG2:
            s = prev[i] + prev2[i]
            return s // 2 if s >= 0 else -((-s) // 2)
        if p == P_MINTHR:
            return self.minthrottle
        if p == P_MINMOTOR:
            return self.minmotor
        if p == P_MOTOR0:
            return cur[self.names.index("motor[0]")]
        if p == P_INC:
            return cur[i]  # loopIteration is never written in P frames
        if p == P_1500:
            return 1500
        if p == P_VBATREF:
            return self.vbatref
        raise ValueError(p)

    def slow(self, flight_mode_flags, state_flags=0):
        self.out += b"S" + uvb(flight_mode_flags) + uvb(state_flags) + uvb(0) + uvb(1) + uvb(1)
        return self

    def gps_home(self, lat, lon):
        self.home = (lat, lon)
        self.out += b"H" + svb(lat) + svb(lon)
        return self

    def gps_frame(self, time_us, sats, lat, lon, alt, speed=0, course=0):
        self.out += b"G" + uvb(time_us - self.last_time) + uvb(sats) + svb(lat - self.home[0]) + svb(lon - self.home[1])
        self.out += svb(alt) + uvb(speed) + uvb(course)
        return self

    def event_flight_mode(self, new, old):
        self.out += b"E" + bytes([30]) + uvb(new) + uvb(old)
        return self

    def event_disarm(self, reason=1):
        self.out += b"E" + bytes([15]) + uvb(reason)
        return self

    def end(self):
        self.out += b"E\xffEnd of log\x00"
        return self

    def raw(self, data):
        self.out += data
        return self

    def bytes(self):
        return bytes(self.out)


def _hline(name, value):
    return f"H {name}:{value}\n".encode("ascii")


def _field_lines(kind, names, signed, pred, enc):
    return [
        _hline(f"Field {kind} name", ",".join(names)),
        _hline(f"Field {kind} signed", ",".join(map(str, signed))),
        _hline(f"Field {kind} predictor", ",".join(map(str, pred))),
        _hline(f"Field {kind} encoding", ",".join(map(str, enc))),
    ]


def _encode(resid, encs, preds):
    out = bytearray()
    i = 0
    n = len(resid)
    while i < n:
        e = encs[i]
        if preds[i] == P_INC:
            i += 1
        elif e in GROUPED:
            k, fn = GROUPED[e]
            out += fn(resid[i:i + k])
            i += k
        elif e == E_TAG8_8SVB:
            j = i + 1
            while j < n and j < i + 8 and encs[j] == E_TAG8_8SVB:
                j += 1
            out += tag8_8svb(resid[i:j])
            i = j
        else:
            v = resid[i]
            out += {E_SVB: svb, E_UVB: uvb, E_NEG14: neg14, E_NULL: lambda _: b""}[e](v)
            i += 1
    return bytes(out)


def float_hex(f):
    return "0x%08x" % struct.unpack("<I", struct.pack("<f", f))[0]
