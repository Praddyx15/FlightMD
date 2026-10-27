"""
ArduPilot dataflash (.bin) parser on top of pymavlink's DFReader. Maps the messages the
analysers use onto the PX4 topic and column names (see ulog_parser.py), so every
analyser runs on ArduPilot logs unchanged.

Time is each message's TimeUS (boot clock) shifted so the log starts at 0. DFReader's
own _timestamp jumps to GPS/epoch time once the GPS gets a fix, so it isn't used.

Only the message types in FAMILIES are read, each into one preallocated float block
(DFReader's index knows how many there are), and every DataFrame is built once at the
end. Going through to_dict() for every message was most of the parse time and memory.

estimator_status is deliberately not produced. XKF/NKF messages use other field names
and other bit meanings than PX4's innovation_check_flags / solution_status_flags, and a
guessed bitmask would give EKF findings that look exact but aren't. The test ratios do
mean the same thing, so those go to ekf_test_ratios instead.
"""

import logging
import operator
import os
import re
from typing import Callable, Optional

import numpy as np
import pandas as pd

from flightmd_core.models.metadata import FlightMetadata, utc_iso
from flightmd_core.services.airframes import ardupilot_frame
from flightmd_core.services.columns import ColumnBuffer

logger = logging.getLogger(__name__)

_EKF4 = [
    ("sv", "SV"), ("sp", "SP"), ("sh", "SH"), ("sm", "SM"), ("svt", "SVT"),
    ("fault_status", "FS"), ("timeout_status", "TS"), ("solution_status", "SS"),
    ("gps_check_status", "GPS"), ("primary_core", "PI"),
]

# family -> (message types, instance field, [(column, source field(s))])
# A tuple of sources means "first one the message has": names changed between releases.
FAMILIES = {
    "imu": (("IMU", "IMU2", "IMU3"), "I", [
        ("rollspeed", "GyrX"), ("pitchspeed", "GyrY"), ("yawspeed", "GyrZ"),
        ("x", "AccX"), ("y", "AccY"), ("z", "AccZ"),
    ]),
    "bat": (("BAT", "BAT2"), "Inst", [
        ("voltage_v", "Volt"), ("current_a", "Curr"), ("temperature", "Temp"),
        ("current_consumed_mah", "CurrTot"), ("remaining", "RemPct"),
        ("internal_resistance_estimate", "Res"),
    ]),
    "bcl": (("BCL",), "Instance", [(f"cell{k}", f"V{k}") for k in range(1, 15)]),
    "gps": (("GPS", "GPS2"), "I", [
        ("lat", "Lat"), ("lon", ("Lng", "Lon")), ("alt", "Alt"), ("satellites_used", "NSats"),
        ("hdop", "HDop"), ("fix_type", "Status"), ("gwk", "GWk"), ("gms", "GMS"),
    ]),
    "gpa": (("GPA", "GPA2"), "I", [("eph", "HAcc"), ("epv", "VAcc"), ("s_variance_m_s", "SAcc")]),
    # pre-4.0 logs use numbered message names instead of an instance feild
    "esc": (("ESC", *(f"ESC{i}" for i in range(1, 9))), "Instance", [
        ("esc_rpm", "RPM"), ("esc_voltage", "Volt"), ("esc_current", "Curr"), ("esc_temperature", "Temp"),
    ]),
    "vibe": (("VIBE",), "IMU", [
        ("vibration_x", "VibeX"), ("vibration_y", "VibeY"), ("vibration_z", "VibeZ"),
        ("clip", "Clip"), ("clip0", "Clip0"), ("clip1", "Clip1"), ("clip2", "Clip2"),
    ]),
    "xkf4": (("XKF4",), "C", _EKF4),
    "nkf4": (("NKF4",), "C", _EKF4),
    "rate": (("RATE",), None, [("roll", "RDes"), ("pitch", "PDes"), ("yaw", "YDes")]),
    "powr": (("POWR",), None, [("voltage5v_v", "Vcc"), ("servo_rail_v", "VServo"), ("power_flags", "Flags")]),
}

TYPE_FAMILY = {t: fam for fam, (types, _, _) in FAMILIES.items() for t in types}
# instance of the numbered pre-4.0 types; NKF4 is core 0, not instance 3
TYPE_INSTANCE = {
    "IMU2": 1, "IMU3": 2, "BAT2": 1, "GPS2": 1, "GPA2": 1,
    **{f"ESC{i}": i - 1 for i in range(1, 9)},
}
EVENT_TYPES = {"MODE", "MSG", "EV", "ARM"}
WANTED_TYPES = set(TYPE_FAMILY) | EVENT_TYPES

# LogEvent ids from ArduPilot's AP_Logger
EV_ARMED, EV_DISARMED, EV_LAND_COMPLETE, EV_NOT_LANDED = 10, 11, 18, 28

GPS_EPOCH_UNIX_S = 315_964_800  # 1980-01-06
GPS_LEAP_S = 18                 # GPS - UTC since 2017

# BCL cells are mV; unused cells are logged as 0xFFFF
NO_CELL_MV = 65535

# startup banner with the board's 96-bit UID, e.g. "CubeOrange 0035002A 30395112 34313234"
BOARD_LINE = re.compile(r"^([A-Za-z][\w\-]*) [0-9A-F]{8} [0-9A-F]{8} [0-9A-F]{8}$")

PROGRESS_EVERY = 50_000  # messages
INDEX_SHARE = 0.2        # rough share of the parse spent in DFReader's index pass

_FIRMWARE_TO_VEHICLE_TYPE = {
    "ArduCopter": "Copter",
    "ArduPlane": "Plane",
    "ArduRover": "Rover",
    "ArduSub": "Sub",
    "Blimp": "Blimp",
    "AntennaTracker": "AntennaTracker",
    "APM:Copter": "Copter",
    "APM:Plane": "Plane",
    "APM:Rover": "Rover",
}

# ArduPilot mode name -> nearest PX4 nav_state. Rough by nature: modes that have no
# PX4 counterpart (DRIFT, SPORT, AUTOTUNE, THROW...) are left out and come back as NaN.
_MODE_TO_NAV_STATE = {
    "MANUAL": 0, "ALT_HOLD": 1, "QHOVER": 1, "FBWB": 1,
    "POSHOLD": 2, "QLOITER": 2, "CRUISE": 2,
    "AUTO": 3, "BRAKE": 4, "HOLD": 4,
    "RTL": 5, "SMART_RTL": 5, "AUTO_RTL": 5, "QRTL": 5,
    "ACRO": 10, "QACRO": 10, "GUIDED": 14,
    "STABILIZE": 15, "QSTABILIZE": 15, "FBWA": 15,
    "TAKEOFF": 17, "LAND": 18, "QLAND": 18, "FOLLOW": 19,
}


def ardupilot_nav_state(mode: Optional[str], vehicle: Optional[str]) -> float:
    if not mode:
        return np.nan
    mode = mode.upper()
    # copter LOITER is pilot-flown position hold; plane/rover LOITER is an auto hold
    if mode == "LOITER":
        return 2 if vehicle == "Copter" else 4
    if mode == "CIRCLE":
        return 21 if vehicle == "Copter" else 4
    return _MODE_TO_NAV_STATE.get(mode, np.nan)


def _boot_us(d: dict) -> Optional[int]:
    if d.get("TimeUS") is not None:
        return int(d["TimeUS"])
    if d.get("TimeMS") is not None:
        return int(d["TimeMS"]) * 1000
    return None


def _first(names, has) -> Optional[str]:
    for n in ((names,) if isinstance(names, str) else names):
        if has(n):
            return n
    return None


def _row_getter(msg, inst_field, fields) -> Callable:
    """msg -> (time_us, instance, *fields), NaN for fields the message doesn't have.

    Real binary messages are read straight from their unpacked elements with the
    format's own multipliers (that's what DFMessage.__getattr__ does, minus the
    per-field overhead). Text-log messages hold strings, so they go through getattr;
    anything else (test fakes) through to_dict().
    """
    mtype = msg.get_type()
    fallback_inst = TYPE_INSTANCE.get(mtype, 0)
    fmt = getattr(msg, "fmt", None)

    if fmt is None:
        def from_dict(m):
            d = m.to_dict()
            inst = d.get(inst_field) if inst_field else None
            vals = []
            for src in fields:
                name = _first(src, lambda n: d.get(n) is not None)
                vals.append(d[name] if name else None)
            return (_boot_us(d), fallback_inst if inst is None else inst, *vals)
        return from_dict

    cols = fmt.colhash
    time_name = _first(("TimeUS", "TimeMS"), cols.__contains__)
    names = [time_name, inst_field if inst_field in cols else None]
    names += [_first(src, cols.__contains__) for src in fields]

    if not msg._apply_multiplier:
        def from_attrs(m):
            row = [getattr(m, n) if n else None for n in names]
            if row[1] is None:
                row[1] = fallback_inst
            if time_name == "TimeMS" and row[0] is not None:
                row[0] *= 1000
            return row
        return from_attrs

    idx = [cols[n] for n in names if n]
    mul, div = [], []
    for n in names:
        if not n:
            continue
        m = 1000.0 if n == "TimeMS" else fmt.msg_mults[cols[n]]
        # divide for the fractional ones, like DFReader does: 1e-2 isn't exact, 100 is
        mul.append(m if m is not None and m >= 1 else 1.0)
        div.append(1.0 / m if m is not None and 0 < m < 1 else 1.0)
    take = operator.itemgetter(*idx)

    if len(idx) == len(names) and len(idx) > 1 and all(v == 1.0 for v in mul + div):
        return take  # IMU and friends: plain floats, nothing to fill in

    scale_mul, scale_div = np.array(mul), np.array(div)
    pos = [k for k, n in enumerate(names) if n]
    width = len(names)

    def from_elements(m):
        row = np.full(width, np.nan)
        row[pos] = np.asarray(take(m._elements), dtype=np.float64) * scale_mul / scale_div
        if names[1] is None:
            row[1] = fallback_inst
        return row
    return from_elements


class ArduPilotBinParser:
    """Same interface as ULogParser: .parse(path) -> (topics, params, metadata)."""

    _progress: Optional[Callable[[float], None]] = None

    def _open_reader(self, path):
        from pymavlink import DFReader

        report = self._progress
        if report is None:
            return DFReader.DFReader_binary(path)

        def indexed(pct):
            report(INDEX_SHARE * pct / 100)
        return DFReader.DFReader_binary(path, progress_callback=indexed)

    def parse(
        self,
        bin_path: str,
        progress: Optional[Callable[[float], None]] = None,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        """progress, if given, is called now and then with the fraction done (0-1)."""
        if not os.path.exists(bin_path):
            raise FileNotFoundError(f"ArduPilot log file not found: {bin_path}")

        logger.info(f"Parsing ArduPilot dataflash log: {bin_path}")
        self._progress = progress
        reader = self._open_reader(bin_path)

        bufs: dict[str, ColumnBuffer] = {}
        getters: dict = {}
        arm_msgs, arm_evs, land, modes = [], [], [], []
        firmware_version = board = frame_text = None
        event_times = []
        last_us = None
        n = 0

        while True:
            msg = reader.recv_match(type=WANTED_TYPES)
            if msg is None:
                break
            n += 1
            if progress is not None and n % PROGRESS_EVERY == 0:
                pct = getattr(reader, "percent", None)
                if pct is not None:
                    progress(INDEX_SHARE + (1 - INDEX_SHARE) * pct / 100)

            mtype = msg.get_type()
            fam = TYPE_FAMILY.get(mtype)
            if fam is not None:
                key = (fam, getattr(msg, "fmt", None) or mtype)
                get = getters.get(key)
                if get is None:
                    _, inst_field, fields = FAMILIES[fam]
                    get = getters[key] = _row_getter(msg, inst_field, [src for _, src in fields])
                buf = bufs.get(fam)
                if buf is None:
                    types, _, fields = FAMILIES[fam]
                    buf = bufs[fam] = ColumnBuffer(
                        ["timestamp", "inst", *(c for c, _ in fields)], _type_count(reader, types))
                buf.append(get(msg))
                continue

            d = msg.to_dict()
            ts = _boot_us(d)
            if ts is None:
                # very old logs: MSG and friends carry no time at all
                ts = last_us or 0
            else:
                last_us = ts
                event_times.append(ts)

            if mtype == "MODE":
                # DFReader turns the mode number into a name once it knows the vehicle
                name = getattr(reader, "flightmode", None)
                if not isinstance(name, str) or name == "UNKNOWN":
                    name = d.get("Mode", d.get("ModeNum"))
                if name is not None:
                    modes.append((ts, str(name)))

            elif mtype == "MSG":
                text = str(d.get("Message") or "").strip()
                if firmware_version is None and text.startswith(tuple(_FIRMWARE_TO_VEHICLE_TYPE)):
                    firmware_version = text
                elif board is None and (m := BOARD_LINE.match(text)):
                    board = m.group(1)
                elif frame_text is None and text.startswith("Frame: "):
                    frame_text = text[len("Frame: "):].strip()

            elif mtype == "ARM":
                if d.get("ArmState") is not None:
                    arm_msgs.append((ts, bool(d["ArmState"])))

            elif mtype == "EV":
                ev = d.get("Id")
                if ev in (EV_ARMED, EV_DISARMED):
                    arm_evs.append((ts, ev == EV_ARMED))
                elif ev in (EV_LAND_COMPLETE, EV_NOT_LANDED):
                    land.append((ts, ev == EV_LAND_COMPLETE))

        params = {k: float(v) for k, v in (getattr(reader, "params", None) or {}).items() if _is_numeric(v)}
        vehicle_type = _vehicle_type_from_firmware_string(firmware_version)

        frames = {}
        for fam, b in bufs.items():
            df = b.frame()
            # a type with no time field at all can't be placed on the log's clock
            frames[fam] = df[df["timestamp"].notna()]
        times = [df["timestamp"] for df in frames.values() if len(df)]
        lo = [float(t.min()) for t in times] + event_times
        hi = [float(t.max()) for t in times] + event_times
        first_us = int(min(lo)) if lo else None
        last_seen = int(max(hi)) if hi else None
        t0 = first_us or 0

        frames = {
            fam: df.assign(timestamp=(df["timestamp"] - t0).round().astype("int64"))
            for fam, df in frames.items()
        }

        topics: dict[str, pd.DataFrame] = {}
        _imu_topics(topics, frames.get("imu"))
        _battery_topics(topics, frames.get("bat"), frames.get("bcl"), params)
        log_start_utc = _gps_topics(topics, frames.get("gps"), frames.get("gpa"))
        _vibration_topics(topics, frames.get("vibe"))
        _ekf_topics(topics, frames.get("xkf4"), frames.get("nkf4"), params)

        esc = frames.get("esc")
        if esc is not None:
            esc_frames = {}
            for i, df in _instances(esc).items():
                df = df.dropna(how="all", subset=["esc_rpm", "esc_voltage", "esc_current", "esc_temperature"])
                if not df.empty:
                    esc_frames[i] = df
            if esc_frames:
                topics["esc_status"] = merge_esc(esc_frames)

        rate = frames.get("rate")
        if rate is not None and not rate.empty:
            # RATE logs deg/s; PX4's setpoint topic is rad/s
            sp = rate[["timestamp", "roll", "pitch", "yaw"]].reset_index(drop=True)
            sp[["roll", "pitch", "yaw"]] = np.radians(sp[["roll", "pitch", "yaw"]])
            topics["vehicle_rates_setpoint"] = sp

        powr = frames.get("powr")
        if powr is not None:
            power = powr.drop(columns="inst").dropna(axis=1, how="all").reset_index(drop=True)
            if len(power.columns) > 1:
                topics["system_power"] = power

        status, arm_count = _vehicle_status(arm_msgs or arm_evs, modes, vehicle_type, t0)
        if status is not None:
            topics["vehicle_status"] = status
        if land:
            topics["vehicle_land_detected"] = pd.DataFrame(
                [(ts - t0, v) for ts, v in sorted(land)], columns=["timestamp", "landed"])

        duration_s = (last_seen - first_us) / 1e6 if first_us is not None and last_seen is not None else 0.0
        metadata = FlightMetadata(
            duration_seconds=round(duration_s, 2),
            firmware_version=firmware_version,
            hardware_id=board,
            airframe_name=ardupilot_frame(params, vehicle_type) or frame_text,
            vehicle_type=vehicle_type,
            log_start_utc=log_start_utc,
            arm_count=arm_count,
            flight_modes_used=sorted({name for _, name in modes}),
            available_topics=sorted(topics.keys()),
        )

        logger.info(
            f"Parsed ArduPilot log: {len(topics)} topics, {len(params)} params, "
            f"duration={duration_s:.1f}s"
        )
        return topics, params, metadata


def _type_count(reader, types) -> int:
    """How many messages of these types the reader's index found (0 if it can't say)."""
    counts = getattr(reader, "counts", None)
    ids = getattr(reader, "name_to_id", None)
    total = 0
    for t in types:
        try:
            # DFReader_binary: list by type id; DFReader_text: dict by name
            total += counts[t] if isinstance(counts, dict) else counts[ids[t]]
        except (TypeError, KeyError, IndexError):
            pass
    return total


def _instances(df: pd.DataFrame) -> dict[int, pd.DataFrame]:
    return {
        int(i): g.drop(columns="inst").reset_index(drop=True)
        for i, g in df.groupby("inst", sort=True)
    }


def store_instances(topics, name, frames: dict[int, pd.DataFrame]) -> None:
    """Lowest instance under the bare name, the others as name_<instance>."""
    for k, i in enumerate(sorted(frames)):
        df = frames[i].reset_index(drop=True)
        topics[name if k == 0 else f"{name}_{i}"] = df


def merge_esc(frames: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """
    ESC instances are logged one message each, at slightly different times, so an exact
    timestamp join leaves every row mostly empty. Bin all of them onto one time base
    (bin = slowest instance's median interval), average inside a bin, and start where
    every ESC has reported. Gaps stay NaN.
    """
    dts = [np.median(np.diff(f["timestamp"].to_numpy())) for f in frames.values() if len(f) > 1]
    width = max(int(max(dts)) if dts else 100_000, 1_000)
    t0 = min(int(f["timestamp"].min()) for f in frames.values())

    out = None
    for i in sorted(frames):
        f = frames[i]
        b = (f["timestamp"].to_numpy() - t0) // width
        g = f.drop(columns="timestamp").groupby(b).mean()
        g.columns = [f"esc[{i}].{c}" for c in g.columns]
        out = g if out is None else out.join(g, how="outer")
    out = out.sort_index()

    first = max(
        out[[c for c in out.columns if c.startswith(f"esc[{i}].")]].notna().any(axis=1).idxmax()
        for i in frames
    )
    out = out.loc[first:]
    out.insert(0, "timestamp", t0 + out.index.to_numpy() * width)
    out["esc_count"] = len(frames)
    return out.reset_index(drop=True)


def _imu_topics(topics, imu) -> None:
    if imu is None:
        return
    accel, gyro = {}, None
    for i, df in _instances(imu).items():
        g = df[["timestamp", "rollspeed", "pitchspeed", "yawspeed"]].dropna(
            subset=["rollspeed", "pitchspeed", "yawspeed"], how="all")
        a = df[["timestamp", "x", "y", "z"]].dropna(subset=["x", "y", "z"], how="all")
        if gyro is None and not g.empty:
            gyro = g
        if not a.empty:
            accel[i] = a
    if gyro is not None:
        topics["vehicle_angular_velocity"] = gyro.reset_index(drop=True)
    store_instances(topics, "sensor_accel", accel)


def _battery_topics(topics, bat, bcl, params) -> None:
    if bat is None:
        return
    cells = _instances(bcl) if bcl is not None else {}
    batteries = {}
    for i, df in _instances(bat).items():
        df = df.dropna(subset=["voltage_v", "current_a"], how="all")
        if df.empty:
            continue
        # RemPct is the autopilot's own estimate (4.1+). Not derived from CurrTot
        # here: that would make the capacity-fade check compare a number with itself.
        if df["remaining"].notna().any():
            df["remaining"] = df["remaining"] / 100.0
        else:
            df = df.drop(columns="remaining")
        if df["internal_resistance_estimate"].isna().all():
            df = df.drop(columns="internal_resistance_estimate")
        rated = params.get("BATT_CAPACITY" if i == 0 else f"BATT{i + 1}_CAPACITY")
        if rated and rated > 0:
            df["capacity"] = rated
        if i in cells:
            df = _with_cells(df, cells[i])
        batteries[i] = df
    store_instances(topics, "battery_status", batteries)


def _with_cells(bat: pd.DataFrame, bcl: pd.DataFrame) -> pd.DataFrame:
    mv = bcl[[f"cell{k}" for k in range(1, 15)]]
    mv = mv.where((mv > 0) & (mv < NO_CELL_MV))
    live = [c for c in mv.columns if mv[c].notna().any()]
    if not live:
        return bat
    volts = pd.DataFrame({"timestamp": bcl["timestamp"]})
    for k, c in enumerate(live):
        volts[f"voltage_cell_v[{k}]"] = mv[c] / 1000.0
    # BCL is logged right after BAT, same tick
    out = pd.merge_asof(bat.sort_values("timestamp"), volts.sort_values("timestamp"),
                        on="timestamp", direction="nearest", tolerance=100_000)
    out["cell_count"] = len(live)
    return out


def _gps_topics(topics, gps, gpa) -> Optional[str]:
    """vehicle_gps_position per receiver; returns log_start_utc from the first 3D fix."""
    if gps is None:
        return None
    log_start_utc = None
    fixed = gps[(gps["fix_type"] >= 3) & (gps["gwk"] > 0)]
    if not fixed.empty:
        r = fixed.iloc[0]
        gms = 0 if np.isnan(r["gms"]) else r["gms"]
        utc = (GPS_EPOCH_UNIX_S + int(r["gwk"]) * 604_800 - GPS_LEAP_S) * 1_000_000 + int(gms) * 1000
        # r.timestamp is already log-relative
        log_start_utc = utc_iso(utc - int(r["timestamp"]))

    acc = _instances(gpa) if gpa is not None else {}
    receivers = {}
    for i, df in _instances(gps).items():
        df = df.drop(columns=["gwk", "gms"])
        # no fix value = not a usable GPS row
        df = df.dropna(subset=["lat", "lon", "fix_type"])
        if df.empty:
            continue
        # DFReader already scales Lat/Lng to degrees and Alt to metres;
        # the PX4 topic wants degE7 and mm. GPS Status uses the same 0-6 scale as fix_type.
        df["lat"] = (df["lat"] * 1e7).round().astype("int64")
        df["lon"] = (df["lon"] * 1e7).round().astype("int64")
        df["alt"] = (df["alt"] * 1000.0).round()
        df["fix_type"] = df["fix_type"].astype("int64")
        if i in acc:
            a = acc[i].dropna(how="all", subset=["eph", "epv", "s_variance_m_s"])
            if not a.empty:
                # GPA is written with the same TimeUS as its GPS row
                df = pd.merge_asof(df.sort_values("timestamp"), a.sort_values("timestamp"),
                                   on="timestamp", direction="nearest", tolerance=50_000)
        receivers[i] = df
    store_instances(topics, "vehicle_gps_position", receivers)
    return log_start_utc


def _vibration_topics(topics, vibe) -> None:
    """VIBE -> vibration: vibration_x/y/z (m/s^2) and cumulative clipping_<imu> counts.
    4.1+ logs one VIBE per IMU with a single Clip; older ones Clip0-2 on one message."""
    if vibe is None or vibe.empty:
        return
    per_imu = {}
    for i, df in _instances(vibe).items():
        out = df[["timestamp", "vibration_x", "vibration_y", "vibration_z"]].copy()
        if df["clip"].notna().any():
            out[f"clipping_{i}"] = df["clip"]
        for k in range(3):
            if df[f"clip{k}"].notna().any():
                out[f"clipping_{k}"] = df[f"clip{k}"]
        per_imu[i] = out

    first = min(per_imu)
    bare = per_imu[first].sort_values("timestamp")
    for i, df in per_imu.items():
        if i == first or f"clipping_{i}" not in df.columns:
            continue
        # counters only go up, so the last value before each row is the right one
        bare = pd.merge_asof(bare, df[["timestamp", f"clipping_{i}"]].sort_values("timestamp"),
                             on="timestamp", direction="backward")
    per_imu[first] = bare
    store_instances(topics, "vibration", per_imu)


def _ekf_topics(topics, xkf4, nkf4, params) -> None:
    """XKF4 (EKF3) or NKF4 (EKF2) of the EKF the vehicle flew on -> ekf_test_ratios.

    ArduPilot logs the square root of each innovation test ratio (Mission Planner's
    "variance"); squared here so the columns mean what PX4's do: 1.0 = rejected.
    """
    ekf_type = int(params.get("AHRS_EKF_TYPE", 3) or 3)
    src = nkf4 if (ekf_type == 2 and nkf4 is not None) or xkf4 is None else xkf4
    if src is None or src.empty:
        return

    cores = _instances(src)
    pi = src["primary_core"].dropna()
    pi = pi[pi >= 0]
    primary = int(pi.mode().iloc[0]) if not pi.empty else min(cores)
    if primary not in cores:
        primary = min(cores)

    frames = {}
    for i, df in cores.items():
        out = pd.DataFrame({"timestamp": df["timestamp"]})
        for col, name in [("sv", "vel"), ("sp", "pos"), ("sh", "hgt"), ("sm", "mag"), ("svt", "tas")]:
            out[f"{name}_test_ratio"] = df[col] ** 2
        for col in ["fault_status", "timeout_status", "solution_status", "gps_check_status", "primary_core"]:
            out[col] = df[col]
        frames[i] = out

    # primary under the bare name, the one it displaced under the primary's number
    lowest = min(cores)
    topics["ekf_test_ratios"] = frames.pop(primary)
    for i, df in frames.items():
        topics[f"ekf_test_ratios_{primary if i == lowest else i}"] = df


def _vehicle_status(arm, modes, vehicle_type, t0):
    """vehicle_status rows from arm/disarm and mode changes; arming_state only when the
    log has any arm information. Returns (df or None, arm count)."""
    if not arm and not modes:
        return None, 0
    arm = sorted(arm)
    events = sorted([(ts, 0, v) for ts, v in arm] + [(ts, 1, v) for ts, v in modes], key=lambda e: e[:2])

    # before the first event the vehicle was in the opposite state
    armed = (not arm[0][1]) if arm else None
    nav = np.nan
    rows, count = [], 0
    if arm:
        rows.append((0, 2 if armed else 1, nav))
    for ts, kind, v in events:
        if kind == 0:
            if v and not armed:
                count += 1
            armed = v
        else:
            nav = ardupilot_nav_state(v, vehicle_type)
        rows.append((ts - t0, (2 if armed else 1) if armed is not None else np.nan, nav))

    df = pd.DataFrame(rows, columns=["timestamp", "arming_state", "nav_state"])
    if not arm:
        df = df.drop(columns="arming_state")
    else:
        df["arming_state"] = df["arming_state"].astype("int64")
    return df, count


def _is_numeric(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _vehicle_type_from_firmware_string(firmware_version: Optional[str]) -> Optional[str]:
    """The startup MSG line ("ArduCopter V4.3.5 (02ff7ea3)") is the only place a
    dataflash log records the vehicle type."""
    if not firmware_version:
        return None
    for prefix, vehicle_type in _FIRMWARE_TO_VEHICLE_TYPE.items():
        if prefix in firmware_version:
            return vehicle_type
    return None
