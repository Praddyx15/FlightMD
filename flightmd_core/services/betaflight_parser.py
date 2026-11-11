"""
Betaflight / INAV blackbox (.bbl, .bfl, LOGxxx.TXT) parser. A native decoder for the
documented blackbox format: "H name:value" header lines that define every field's
predictor and encoding, then I/P main frames, S slow frames, G/H GPS frames and E events.
Written from the format description (Cleanflight's "Blackbox logging internals" and the
Betaflight field definitions); no blackbox-tools code is used.

Output follows the PX4 topic names (see ulog_parser.py):
  vehicle_angular_velocity  gyroADC, deg/s -> rad/s
  vehicle_rates_setpoint    setpoint[0..2], deg/s -> rad/s
  sensor_accel              accSmooth / acc_1G, in m/s^2
  actuator_outputs          motor[] as logged (DShot 0-2047 or PWM us)
  esc_status                eRPM[] fields, or debug[] in DSHOT_RPM_TELEMETRY mode
  battery_status            vbatLatest / amperageLatest (INAV: vbat / amperage)
  vehicle_gps_position      G frames
  vehicle_status            Betaflight only: the arm switch (BOXARM) from S frames and
                            flight-mode events

A file can hold several logs (one per arm); the biggest one is analysed and the rest are
mentioned in parse_warnings. Header values that are numbers become params.
"""

import logging
import math
import os
import re
import struct
from array import array
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from flightmd_core.models.metadata import MIN_EPOCH_US, FlightMetadata, utc_iso

logger = logging.getLogger(__name__)

LOG_START = b"H Product:Blackbox flight data recorder by Nicholas Sherlock"

# predictors
PRED_ZERO, PRED_PREVIOUS, PRED_STRAIGHT_LINE, PRED_AVERAGE_2, PRED_MINTHROTTLE = 0, 1, 2, 3, 4
PRED_MOTOR_0, PRED_INC, PRED_HOME_COORD, PRED_1500, PRED_VBATREF = 5, 6, 7, 8, 9
PRED_LAST_MAIN_FRAME_TIME, PRED_MINMOTOR = 10, 11

# encodings
ENC_SIGNED_VB, ENC_UNSIGNED_VB, ENC_NEG_14BIT = 0, 1, 3
ENC_TAG8_8SVB, ENC_TAG2_3S32, ENC_TAG8_4S16, ENC_NULL, ENC_TAG2_3SVARIABLE = 6, 7, 8, 9, 10

# event frame types
EV_SYNC_BEEP, EV_INFLIGHT_ADJUSTMENT, EV_LOGGING_RESUME, EV_DISARM = 0, 13, 14, 15
EV_GTUNE_RESULT, EV_FLIGHT_MODE, EV_LOG_END = 20, 30, 255
END_OF_LOG = b"End of log\x00"

# sanity limits between consecutve main frames; anything bigger is a corrupt frame
MAX_ITERATION_JUMP = 5000
MAX_TIME_JUMP_US = 10_000_000

# Betaflight box ids in the S-frame flag mask (it's rcModeActivationMask since 3.5)
BOX_ARM, BOX_ANGLE, BOX_HORIZON = 0, 1, 2

# debug_mode number of DSHOT_RPM_TELEMETRY in Betaflight 4.2 - 4.5 (eRPM/100 per motor)
DEBUG_DSHOT_RPM_TELEMETRY = 45

GRAVITY = 9.80665
BATTERY_BIN_US = 10_000   # vbat/amperage only change at ~50 Hz; 100 Hz is plenty

U32 = 0xFFFFFFFF


class BlackboxError(ValueError):
    pass


class _Truncated(Exception):
    pass


def read_uvb(buf, pos):
    """Unsigned variable byte: 7 bits per byte, low bits first, top bit = more follows."""
    result = shift = 0
    for _ in range(5):
        if pos >= len(buf):
            raise _Truncated
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 128:
            return result & U32, pos
        shift += 7
    raise BlackboxError("variable byte value longer than 32 bits")


def zigzag_decode(u: int) -> int:
    return (u >> 1) ^ -(u & 1)


def read_svb(buf, pos):
    u, pos = read_uvb(buf, pos)
    return zigzag_decode(u), pos


def sign_extend(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def _byte(buf, pos):
    if pos >= len(buf):
        raise _Truncated
    return buf[pos]


def read_neg_14bit(buf, pos):
    u, pos = read_uvb(buf, pos)
    return -sign_extend(u, 14), pos


def _read_sized3(buf, pos, lead):
    out = []
    for _ in range(3):
        n = (lead & 3) + 1
        if pos + n > len(buf):
            raise _Truncated
        out.append(sign_extend(int.from_bytes(buf[pos:pos + n], "little"), 8 * n))
        pos += n
        lead >>= 2
    return out, pos


def read_tag2_3s32(buf, pos):
    lead = _byte(buf, pos)
    pos += 1
    sel = lead >> 6
    if sel == 0:
        return [sign_extend(lead >> 4, 2), sign_extend(lead >> 2, 2), sign_extend(lead, 2)], pos
    if sel == 1:
        b = _byte(buf, pos)
        return [sign_extend(lead, 4), sign_extend(b >> 4, 4), sign_extend(b, 4)], pos + 1
    if sel == 2:
        b1, b2 = _byte(buf, pos), _byte(buf, pos + 1)
        return [sign_extend(lead, 6), sign_extend(b1, 6), sign_extend(b2, 6)], pos + 2
    return _read_sized3(buf, pos, lead)


def read_tag2_3svariable(buf, pos):
    lead = _byte(buf, pos)
    pos += 1
    sel = lead >> 6
    if sel == 0:
        return [sign_extend(lead >> 4, 2), sign_extend(lead >> 2, 2), sign_extend(lead, 2)], pos
    if sel == 1:
        # ss11 1112 | 2222 3333
        b = _byte(buf, pos)
        bits = ((lead & 0x3F) << 8) | b
        return [sign_extend(bits >> 9, 5), sign_extend(bits >> 4, 5), sign_extend(bits, 4)], pos + 1
    if sel == 2:
        # ss11 1111 | 1122 2222 | 2333 3333
        bits = ((lead & 0x3F) << 16) | (_byte(buf, pos) << 8) | _byte(buf, pos + 1)
        return [sign_extend(bits >> 14, 8), sign_extend(bits >> 7, 7), sign_extend(bits, 7)], pos + 2
    return _read_sized3(buf, pos, lead)


def read_tag8_4s16(buf, pos, version: int = 2):
    """Header byte with a 2-bit size per field (0, 4, 8 or 16 bits). Data version 2 packs
    the fields as one big-endian nibble stream; version 1 used whole little-endian bytes."""
    head = _byte(buf, pos)
    pos += 1
    sizes = [(0, 4, 8, 16)[(head >> (2 * i)) & 3] for i in range(4)]
    if version < 2:
        out = []
        i = 0
        while i < 4:
            s = sizes[i]
            if s == 0:
                out.append(0)
            elif s == 4:
                # v1 always packs two 4-bit fields into one byte, low nibble first
                b = _byte(buf, pos)
                pos += 1
                out += [sign_extend(b, 4), sign_extend(b >> 4, 4)]
                i += 1
            elif s == 8:
                out.append(sign_extend(_byte(buf, pos), 8))
                pos += 1
            else:
                out.append(sign_extend(_byte(buf, pos) | (_byte(buf, pos + 1) << 8), 16))
                pos += 2
            i += 1
        return out[:4], pos

    nbytes = (sum(sizes) + 7) // 8
    if pos + nbytes > len(buf):
        raise _Truncated
    stream = int.from_bytes(buf[pos:pos + nbytes], "big")
    left = nbytes * 8
    out = []
    for s in sizes:
        if s:
            left -= s
            out.append(sign_extend(stream >> left, s))
        else:
            out.append(0)
    return out, pos + nbytes


def read_tag8_8svb(buf, pos, count: int):
    if count == 1:
        v, pos = read_svb(buf, pos)
        return [v], pos
    head = _byte(buf, pos)
    pos += 1
    out = []
    for i in range(count):
        if head & (1 << i):
            v, pos = read_svb(buf, pos)
            out.append(v)
        else:
            out.append(0)
    return out, pos


class FrameDef:
    def __init__(self, names, signed, predictor, encoding):
        n = len(names)
        if len(predictor) < n or len(encoding) < n:
            raise BlackboxError(f"field definition is incomplete ({n} names, {len(predictor)} predictors)")
        self.names = names
        self.index = {name: i for i, name in enumerate(names)}
        self.signed = (signed + [0] * n)[:n]
        self.predictor = predictor[:n]
        self.encoding = encoding[:n]


def _ints(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip() != ""]


def parse_header(data: bytes, pos: int) -> tuple[dict[str, str], int]:
    headers = {}
    while data.startswith(b"H ", pos):
        end = data.find(b"\n", pos)
        if end < 0:
            end = len(data)
        name, _, value = data[pos + 2:end].decode("latin-1").rstrip("\r").partition(":")
        headers[name.strip()] = value.strip()
        pos = end + 1
    return headers, pos


def frame_defs(headers: dict[str, str]) -> dict[str, FrameDef]:
    if "Field I name" not in headers:
        raise BlackboxError("blackbox header has no 'Field I name' line")
    defs = {}
    for kind in "IPSGH":
        names_src = "I" if kind == "P" else kind
        if f"Field {names_src} name" not in headers or f"Field {kind} predictor" not in headers:
            continue
        names = headers[f"Field {names_src} name"].split(",")
        signed = _ints(headers.get(f"Field {names_src} signed", ""))
        defs[kind] = FrameDef(
            names, signed,
            _ints(headers[f"Field {kind} predictor"]),
            _ints(headers.get(f"Field {kind} encoding", "")),
        )
    if "P" not in defs:
        raise BlackboxError("blackbox header has no P frame definition")
    return defs


def split_logs(data: bytes) -> list[tuple[int, int]]:
    starts = []
    pos = data.find(LOG_START)
    while pos >= 0:
        starts.append(pos)
        pos = data.find(LOG_START, pos + len(LOG_START))
    return [(s, starts[k + 1] if k + 1 < len(starts) else len(data)) for k, s in enumerate(starts)]


def _float_header(value: Optional[str], default: float) -> float:
    if not value:
        return default
    try:
        if value.lower().startswith("0x"):
            return struct.unpack("<f", int(value, 16).to_bytes(4, "little"))[0]
        return float(value)
    except (ValueError, OverflowError):
        return default


def _firmware(headers) -> tuple[str, tuple[int, int, int]]:
    """("betaflight" | "inav" | "cleanflight" | "baseflight" | "unknown", version)"""
    rev = headers.get("Firmware revision", "")
    m = re.search(r"(Betaflight|INAV|Cleanflight|Emuflight|Butterflight)\D*(\d+)\.(\d+)(?:\.(\d+))?", rev, re.I)
    if m:
        name = m.group(1).lower()
        if name in ("emuflight", "butterflight"):
            name = "betaflight"
        return name, (int(m.group(2)), int(m.group(3)), int(m.group(4) or 0))
    kind = headers.get("Firmware type", "").lower()
    return (kind or "unknown"), (0, 0, 0)


class _Decoder:
    """Walks one log session and collects the decoded frames."""

    def __init__(self, data: bytes, headers: dict[str, str], wanted: list[str]):
        self.data = data
        self.headers = headers
        self.defs = frame_defs(headers)
        self.data_version = int(headers.get("Data version", "2") or 2)
        self.i_interval = max(1, int(headers.get("I interval", "32") or 32))
        p = headers.get("P interval", "1") or "1"
        if "/" in p:
            num, denom = p.split("/", 1)
            self.p_num, self.p_denom = int(num), int(denom)
        else:
            self.p_num, self.p_denom = 1, int(p)
        self.p_num, self.p_denom = max(1, self.p_num), max(1, self.p_denom)
        self.minthrottle = int(headers.get("minthrottle", "1150") or 1150)
        motor_out = _ints(headers.get("motorOutput", "")) or [self.minthrottle]
        self.minmotor = motor_out[0]
        self.vbatref = int(headers.get("vbatref", "0") or 0)

        idef = self.defs["I"]
        self.it_idx = idef.index.get("loopIteration", 0)
        self.time_idx = idef.index.get("time", 1)
        self.motor0_idx = idef.index.get("motor[0]")
        self.wanted = [n for n in wanted if n in idef.index]
        self.wanted_idx = [idef.index[n] for n in self.wanted]

        self.markers = set(b"E") | {ord(k) for k in self.defs if k != "P"} | {ord("P")}
        self.rows = array("q")
        self.times = array("q")
        self.gps: list[tuple[int, dict]] = []
        self.slow: list[tuple[int, int]] = []          # (time, flight mode flags)
        self.events: list[tuple[int, int, Any]] = []  # (time, kind, value)
        self.corrupt = 0

    def run(self, pos: int):
        data = self.data
        n = len(data)
        prev = prev2 = None
        main_valid = False
        last_it = last_time = -1
        unwrapped = 0       # last main frame time with the 32-bit rollover taken out
        home = None
        cand = None         # (iteration, time) of the last I frame that didn't fit

        while pos < n:
            kind = data[pos]
            if kind not in self.markers:
                pos += 1
                continue
            start = pos
            pos += 1
            try:
                if kind == 73 or kind == 80:     # 'I', 'P'
                    intra = kind == 73
                    if not intra and prev is None:
                        raise BlackboxError("P frame before any I frame")
                    skipped = 0 if intra else self._skipped(last_it)
                    cur, pos = self._frame(self.defs["I" if intra else "P"], pos, prev, prev2, skipped, home)
                elif kind == 69:                 # 'E'
                    ev, pos = self._event(pos)
                elif kind == 83:                 # 'S'
                    cur, pos = self._frame(self.defs["S"], pos, None, None, 0, home)
                elif kind == 72:                 # 'H'
                    cur, pos = self._frame(self.defs["H"], pos, None, None, 0, home)
                else:                            # 'G'
                    if home is None:
                        raise BlackboxError("G frame before any H frame")
                    cur, pos = self._frame(self.defs["G"], pos, None, None, 0, home, last_time=max(last_time, 0))
            except _Truncated:
                break
            except BlackboxError:
                self.corrupt += 1
                if kind in (73, 80):
                    main_valid = False
                pos = start + 1
                continue

            if kind == 69 and ev[0] == EV_LOG_END:
                break
            # a frame is only believed if the next byte starts another frame
            if pos < n and data[pos] not in self.markers:
                self.corrupt += 1
                if kind in (73, 80):
                    main_valid = False
                pos = start + 1
                continue

            if kind == 73 or kind == 80:
                it, t = cur[self.it_idx], cur[self.time_idx]
                dt = ((t - last_time + 0x80000000) & U32) - 0x80000000
                if kind == 73:
                    ok = last_it < 0 or (0 <= it - last_it < MAX_ITERATION_JUMP and 0 <= dt < MAX_TIME_JUMP_US)
                    if not ok and cand is not None and dt > 0:
                        # two I frames in a row that agree with each other: the log
                        # lost more than the jump limits, carry on from here
                        cdt = ((t - cand[1] + 0x80000000) & U32) - 0x80000000
                        ok = 0 < it - cand[0] < MAX_ITERATION_JUMP and 0 < cdt < MAX_TIME_JUMP_US
                    cand = None if ok else (it, t)
                    main_valid = ok
                else:
                    ok = main_valid and it - last_it <= MAX_ITERATION_JUMP and dt <= MAX_TIME_JUMP_US
                    main_valid = ok
                if ok:
                    unwrapped = t if last_time < 0 else unwrapped + dt
                    last_it, last_time = it, t
                    self.times.append(unwrapped)
                    self.rows.extend([cur[i] for i in self.wanted_idx])
                else:
                    self.corrupt += 1
                if kind == 73:
                    prev = prev2 = cur
                else:
                    prev2, prev = prev, cur
            elif kind == 72:
                home = cur
            elif kind == 71:
                d = self.defs["G"]
                if "time" in d.index:
                    gdt = ((cur[d.index["time"]] - max(last_time, 0) + 0x80000000) & U32) - 0x80000000
                    gt = unwrapped + gdt
                else:
                    gt = unwrapped
                self.gps.append((gt, dict(zip(d.names, cur))))
            elif kind == 83:
                d = self.defs["S"]
                if "flightModeFlags" in d.index:
                    self.slow.append((unwrapped, cur[d.index["flightModeFlags"]]))
            elif kind == 69:
                etype, value = ev
                if etype == EV_LOGGING_RESUME:
                    # logging was paused; accept the jump to the resume point
                    last_it, resume_t = value
                    dt = ((resume_t - last_time + 0x80000000) & U32) - 0x80000000
                    unwrapped = resume_t if last_time < 0 else unwrapped + dt
                    last_time = resume_t
                elif etype in (EV_FLIGHT_MODE, EV_DISARM):
                    self.events.append((unwrapped, etype, value))
        return self

    def _skipped(self, last_it: int) -> int:
        if last_it < 0:
            return 0
        n = 0
        i = last_it + 1
        while not self._should_have(i):
            n += 1
            i += 1
        return n

    def _should_have(self, i: int) -> bool:
        return (i % self.i_interval + self.p_num - 1) % self.p_denom < self.p_num

    def _frame(self, fdef: FrameDef, pos, prev, prev2, skipped, home, last_time=0):
        buf = self.data
        enc, pred, signed = fdef.encoding, fdef.predictor, fdef.signed
        count = len(fdef.names)
        cur = [0] * count
        home_k = 0
        i = 0
        while i < count:
            p = pred[i]
            if p == PRED_INC:
                cur[i] = skipped + 1 + (prev[i] if prev else 0)
                i += 1
                continue
            e = enc[i]
            if e == ENC_SIGNED_VB:
                vals, pos = read_svb(buf, pos)
            elif e == ENC_UNSIGNED_VB:
                vals, pos = read_uvb(buf, pos)
            elif e == ENC_NEG_14BIT:
                vals, pos = read_neg_14bit(buf, pos)
            elif e == ENC_NULL:
                vals = 0
            elif e == ENC_TAG8_8SVB:
                j = i + 1
                while j < count and j < i + 8 and enc[j] == ENC_TAG8_8SVB:
                    j += 1
                vals, pos = read_tag8_8svb(buf, pos, j - i)
            elif e == ENC_TAG2_3S32:
                vals, pos = read_tag2_3s32(buf, pos)
            elif e == ENC_TAG2_3SVARIABLE:
                vals, pos = read_tag2_3svariable(buf, pos)
            elif e == ENC_TAG8_4S16:
                vals, pos = read_tag8_4s16(buf, pos, self.data_version)
            else:
                # elias delta (4/5) never shipped in a release that people fly
                raise BlackboxError(f"unsupported field encoding {e}")

            if not isinstance(vals, list):
                vals = [vals]
            for v in vals:
                if i >= count:
                    break
                p = pred[i]
                if p == PRED_ZERO:
                    pass
                elif p == PRED_PREVIOUS:
                    if prev:
                        v += prev[i]
                elif p == PRED_STRAIGHT_LINE:
                    if prev:
                        v += 2 * prev[i] - prev2[i]
                elif p == PRED_AVERAGE_2:
                    if prev:
                        s = prev[i] + prev2[i]
                        v += s // 2 if s >= 0 else -((-s) // 2)   # C truncates toward zero
                elif p == PRED_MINMOTOR:
                    v += self.minmotor
                elif p == PRED_MINTHROTTLE:
                    v += self.minthrottle
                elif p == PRED_MOTOR_0:
                    if self.motor0_idx is None or self.motor0_idx >= i:
                        raise BlackboxError("motor[0] predictor before motor[0]")
                    v += cur[self.motor0_idx]
                elif p == PRED_VBATREF:
                    v += self.vbatref
                elif p == PRED_1500:
                    v += 1500
                elif p == PRED_HOME_COORD:
                    if home is None or home_k >= len(home):
                        raise BlackboxError("GPS coordinate without a home position")
                    v += home[home_k]
                    home_k += 1
                elif p == PRED_LAST_MAIN_FRAME_TIME:
                    v += last_time
                else:
                    raise BlackboxError(f"unsupported field predictor {p}")
                # the firmware does this arithmetic in 32 bits
                if signed[i]:
                    if v > 0x7FFFFFFF or v < -0x80000000:
                        v = ((v + 0x80000000) & U32) - 0x80000000
                elif v > U32 or v < 0:
                    v &= U32
                cur[i] = v
                i += 1
        return cur, pos

    def _event(self, pos):
        buf = self.data
        etype = _byte(buf, pos)
        pos += 1
        if etype == EV_SYNC_BEEP:
            _, pos = read_uvb(buf, pos)
            return (etype, None), pos
        if etype == EV_FLIGHT_MODE:
            new, pos = read_uvb(buf, pos)
            _, pos = read_uvb(buf, pos)
            return (etype, new), pos
        if etype == EV_DISARM:
            reason, pos = read_uvb(buf, pos)
            return (etype, reason), pos
        if etype == EV_LOGGING_RESUME:
            it, pos = read_uvb(buf, pos)
            t, pos = read_uvb(buf, pos)
            return (etype, (it, t)), pos
        if etype == EV_INFLIGHT_ADJUSTMENT:
            func = _byte(buf, pos)
            pos += 1
            if func & 0x80:
                return (etype, None), pos + 4
            _, pos = read_svb(buf, pos)
            return (etype, None), pos
        if etype == EV_GTUNE_RESULT:
            _, pos = read_svb(buf, pos + 1)
            return (etype, None), pos + 2
        if etype == EV_LOG_END:
            if buf[pos:pos + len(END_OF_LOG)] != END_OF_LOG:
                raise BlackboxError("bytes that only look like an end-of-log event")
            return (etype, None), pos + len(END_OF_LOG)
        raise BlackboxError(f"unknown event type {etype}")


MAIN_FIELDS = (
    [f"gyroADC[{i}]" for i in range(3)]
    + [f"setpoint[{i}]" for i in range(4)]
    + [f"accSmooth[{i}]" for i in range(3)]
    + [f"motor[{i}]" for i in range(8)]
    + [f"eRPM[{i}]" for i in range(8)]
    + [f"debug[{i}]" for i in range(8)]
    + ["vbatLatest", "amperageLatest", "vbat", "amperage"]
)


class BetaflightParser:
    """Same interface as ULogParser: .parse(path) -> (topics, params, metadata)."""

    def parse(self, path: str) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Blackbox log file not found: {path}")

        logger.info(f"Parsing blackbox log: {path}")
        with open(path, "rb") as f:
            data = f.read()

        sessions = split_logs(data)
        if not sessions:
            raise ValueError("No blackbox log header found in this file.")
        warnings = []
        # a session with a broken header can't be decoded at all; skip it
        usable = []
        for k, (a, b) in enumerate(sessions):
            headers, body = parse_header(data, a)
            if "Field I name" in headers:
                usable.append((b - a, k, a, b, headers, body))
        if not usable:
            raise ValueError("The blackbox header is incomplete (no field definitions).")
        _, k, a, b, headers, body = max(usable)
        if len(sessions) > 1:
            warnings.append(
                f"This file holds {len(sessions)} blackbox logs; log {k + 1} (the largest) was analysed."
            )

        try:
            dec = _Decoder(data[a:b], headers, MAIN_FIELDS).run(body - a)
        except BlackboxError as e:
            raise ValueError(f"Can't decode this blackbox log: {e}") from e
        if not dec.times:
            raise ValueError("The blackbox log has no decodable frames.")
        if dec.corrupt:
            warnings.append(f"{dec.corrupt} damaged blackbox frames were skipped.")

        firmware, version = _firmware(headers)
        topics, t0 = self._topics(dec, headers, firmware, version, warnings)
        status = _vehicle_status(dec, t0, firmware, version)
        arm_count, modes = 0, []
        if status is not None:
            topics["vehicle_status"] = status
            armed = (status["arming_state"] == 2).to_numpy(dtype=int)
            arm_count = int(armed[0] + (np.diff(armed) == 1).sum())
            modes = sorted({_MODE_NAMES[int(m)] for m in status["nav_state"].unique()})

        params = _params(headers)
        ts = np.asarray(dec.times, dtype=np.int64)
        metadata = FlightMetadata(
            duration_seconds=round(float(ts[-1] - ts[0]) / 1e6, 2),
            firmware_version=headers.get("Firmware revision") or None,
            hardware_id=headers.get("Board information") or None,
            log_start_utc=_start_utc(headers.get("Log start datetime")),
            arm_count=arm_count,
            flight_modes_used=modes,
            available_topics=sorted(topics.keys()),
            parse_warnings=warnings,
        )
        logger.info(
            f"Parsed blackbox log: {len(topics)} topics, {len(params)} params, "
            f"duration={metadata.duration_seconds:.1f}s"
        )
        return topics, params, metadata

    def _topics(self, dec: _Decoder, headers, firmware, version, warnings):
        cols = dec.wanted
        rows = np.frombuffer(dec.rows, dtype=np.int64).reshape(-1, len(cols)) if cols else np.empty((len(dec.times), 0))
        t_abs = np.asarray(dec.times, dtype=np.int64)
        t0 = int(t_abs[0])
        ts = t_abs - t0
        col = {name: rows[:, k] for k, name in enumerate(cols)}
        topics: dict[str, pd.DataFrame] = {}

        high_res = 10.0 if headers.get("blackbox_high_resolution", "0") == "1" else 1.0
        gyro_scale = _float_header(headers.get("gyro_scale") or headers.get("gyro.scale"), 1.0)
        if firmware == "baseflight":
            # old firmware logs raw gyro counts; the scale turns them into rad/us
            to_rad_s = gyro_scale * 1e6
        else:
            to_rad_s = gyro_scale / high_res * math.pi / 180.0

        if all(f"gyroADC[{i}]" in col for i in range(3)):
            gyro = [col[f"gyroADC[{i}]"] for i in range(3)]
            topics["vehicle_angular_velocity"] = pd.DataFrame({
                "timestamp": ts,
                "rollspeed": gyro[0] * to_rad_s,
                "pitchspeed": gyro[1] * to_rad_s,
                "yawspeed": gyro[2] * to_rad_s,
            })

        if all(f"setpoint[{i}]" in col for i in range(3)):
            sp = [col[f"setpoint[{i}]"] for i in range(3)]
            k = math.pi / 180.0 / high_res
            topics["vehicle_rates_setpoint"] = pd.DataFrame({
                "timestamp": ts, "roll": sp[0] * k, "pitch": sp[1] * k, "yaw": sp[2] * k,
            })

        one_g = _float_header(headers.get("acc_1G"), 0.0)
        if all(f"accSmooth[{i}]" in col for i in range(3)):
            acc = [col[f"accSmooth[{i}]"] for i in range(3)]
            if one_g > 0:
                # z reads +1 g at rest here, -1 g on PX4; the analysers high-pass it anyway
                k = GRAVITY / one_g
                topics["sensor_accel"] = pd.DataFrame({
                    "timestamp": ts, "x": acc[0] * k, "y": acc[1] * k, "z": acc[2] * k,
                })
            else:
                warnings.append("The header has no acc_1G, so the accelerometer couldn't be scaled.")

        motors = [col[f"motor[{i}]"] for i in range(8) if f"motor[{i}]" in col]
        if motors:
            out = pd.DataFrame({"timestamp": ts})
            for i, m in enumerate(motors):
                out[f"output[{i}]"] = m.astype(float)
            out["noutputs"] = len(motors)
            topics["actuator_outputs"] = out

        esc = _esc_status(col, ts, headers, len(motors), firmware, version)
        if esc is not None:
            topics["esc_status"] = esc

        bat = _battery(col, ts, firmware, version)
        if bat is not None:
            topics["battery_status"] = bat
        elif "vbatLatest" in col or "vbat" in col:
            warnings.append(f"Battery voltage units for {firmware} {'.'.join(map(str, version))} aren't known; battery skipped.")

        gps = _gps(dec.gps, t0, firmware, version)
        if gps is not None:
            topics["vehicle_gps_position"] = gps
        return topics, t0


def _esc_status(col, ts, headers, n_motors, firmware, version):
    rpm = [col[f"eRPM[{i}]"] for i in range(8) if f"eRPM[{i}]" in col]
    if not rpm:
        name = headers.get("debug_mode_name", "")
        # the debug_mode numbers move between releases; 45 is only checked for 4.2 - 4.5
        by_number = (not name and headers.get("debug_mode") == str(DEBUG_DSHOT_RPM_TELEMETRY)
                     and firmware == "betaflight" and (4, 2) <= version[:2] <= (4, 5))
        if name == "DSHOT_RPM_TELEMETRY" or by_number:
            rpm = [col[f"debug[{i}]"] for i in range(8) if f"debug[{i}]" in col]
    rpm = rpm[:n_motors] if n_motors else rpm
    if not rpm:
        return None
    poles = _float_header(headers.get("motor_poles"), 14.0) or 14.0
    out = pd.DataFrame({"timestamp": ts})
    for i, r in enumerate(rpm):
        # logged as eRPM / 100; electrical rpm / pole pairs = mechanical rpm
        out[f"esc[{i}].esc_rpm"] = r * 100.0 / (poles / 2.0)
    out["esc_count"] = len(rpm)
    return out


def _battery(col, ts, firmware, version):
    v = col.get("vbatLatest", col.get("vbat"))
    if v is None:
        return None
    if firmware == "inav" or (firmware == "betaflight" and version >= (4, 0, 0)):
        v_scale = 0.01
    elif firmware == "betaflight" and version >= (3, 1, 0):
        v_scale = 0.1
    else:
        # Cleanflight / early Betaflight log raw ADC counts
        return None
    keep = np.r_[True, np.diff(ts // BATTERY_BIN_US) != 0]
    out = pd.DataFrame({"timestamp": ts[keep], "voltage_v": v[keep] * v_scale})
    amps = col.get("amperageLatest", col.get("amperage"))
    if amps is not None:
        out["current_a"] = amps[keep] * 0.01
    return out


def _gps(frames, t0, firmware, version):
    if not frames:
        return None
    rows = []
    for t, f in frames:
        lat, lon = f.get("GPS_coord[0]"), f.get("GPS_coord[1]")
        if lat is None or lon is None:
            continue
        sats = f.get("GPS_numSat", 0)
        alt = f.get("GPS_altitude", 0)
        # some versions declare the altitude unsigned but write a signed value
        if alt > 0x7FFFFFFF:
            alt -= 1 << 32
        if "GPS_fixType" in f:
            # INAV: 0 none, 1 2D, 2 3D
            fix = {0: 0, 1: 2, 2: 3}.get(f["GPS_fixType"], 0)
        else:
            # Betaflight doesn't log a fix type; a position with 4+ satellites is a 3D fix
            fix = 3 if sats >= 4 and (lat or lon) else 0
        row = {
            "timestamp": t - t0, "lat": lat, "lon": lon, "alt": alt,
            "satellites_used": sats, "fix_type": fix,
            "vel_m_s": f.get("GPS_speed", 0) / 100.0,
            "cog_rad": math.radians(f.get("GPS_ground_course", 0) / 10.0),
        }
        if "GPS_hdop" in f:
            row["hdop"] = f["GPS_hdop"] / 100.0
        rows.append(row)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    # Betaflight 4.x logs decimetres, 3.x and INAV whole metres; the topic wants mm
    alt_mm = 100 if firmware == "betaflight" and version >= (4, 0, 0) else 1000
    df["alt"] = df["alt"] * alt_mm
    df = df.astype({"lat": "int64", "lon": "int64", "alt": "int64", "fix_type": "int64"})
    return df.sort_values("timestamp").reset_index(drop=True)


_MODE_NAMES = {10: "Acro", 15: "Angle / Horizon"}


def _vehicle_status(dec: _Decoder, t0: int, firmware, version):
    if firmware != "betaflight" or version < (3, 5, 0):
        # INAV and older Betaflight log the real flight-mode flags there, not the switches
        return None
    changes = list(dec.slow)
    changes += [(t, v) for t, kind, v in dec.events if kind == EV_FLIGHT_MODE]
    disarms = [t for t, kind, _ in dec.events if kind == EV_DISARM]
    if not changes:
        return None
    rows = []
    for t, flags in sorted(changes):
        armed = bool(flags & (1 << BOX_ARM))
        nav = 15 if flags & ((1 << BOX_ANGLE) | (1 << BOX_HORIZON)) else 10
        rows.append((t, 2 if armed else 1, nav))
    for t in disarms:
        nav = next((r[2] for r in reversed(rows) if r[0] <= t), 10)
        rows.append((t, 1, nav))
    rows.sort(key=lambda r: r[0])
    df = pd.DataFrame(rows, columns=["timestamp", "arming_state", "nav_state"])
    df["timestamp"] = (df["timestamp"] - t0).clip(lower=0)
    # print(df.drop_duplicates(["arming_state", "nav_state"]))
    keep = (df[["arming_state", "nav_state"]].diff().abs().sum(axis=1) > 0).to_numpy()
    keep[0] = True
    return df[keep].astype("int64").reset_index(drop=True)


def _params(headers: dict[str, str]) -> dict[str, float]:
    params: dict[str, float] = {}
    for name, value in headers.items():
        # "Data version", "I interval", "Field I name"... describe the log, not the craft
        if " " in name or not value or value.lower().startswith("0x"):
            continue
        parts = value.split(",")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            continue
        if len(nums) == 1:
            params[name] = nums[0]
        elif len(nums) == 3 and name.endswith("PID"):
            for suffix, v in zip("PID", nums):
                params[f"{name}_{suffix}"] = v
        else:
            for i, v in enumerate(nums):
                params[f"{name}[{i}]"] = v
    return params


def _start_utc(value: Optional[str]) -> Optional[str]:
    """'Log start datetime' is 0000-01-01... when the board has no clock."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    us = dt.timestamp() * 1e6
    return utc_iso(us) if us >= MIN_EPOCH_US else None


def looks_like_blackbox(header: bytes) -> bool:
    return LOG_START in header
