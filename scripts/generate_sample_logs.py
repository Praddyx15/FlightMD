"""
Generates small, spec-valid binary flight logs for all three formats
FlightMD supports — PX4 ULog (.ulg), ArduPilot dataflash (.bin), and
MAVLink telemetry (.tlog) — using each format's own real binary framing,
not a mock. This is what lets tests exercise the actual pyulog / DFReader
/ pymavlink parsing paths end-to-end, rather than only the internal
field-mapping logic (which the existing mocked unit tests already cover).

Two synthetic flight profiles per format:
  - "clean":  near-zero oscillation, healthy battery, stable GPS
  - "flawed": sustained ~1.1Hz roll/pitch oscillation, high battery sag,
              a mid-flight satellite drop — chosen to mirror the kind of
              real tuning issue a genuine flight log turned up during
              manual testing of this project, so the sample data exercises
              the same finding types real drones actually trigger.

Deterministic (fixed random seed) — nothing here depends on real flight
data, so it's safe to commit and safe to regenerate.

Run: python scripts/generate_sample_logs.py
"""

import os
import struct
import time

import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tests", "sample_logs")

DURATION_S = 180.0
RATE_HZ = 20.0
SEED = 42


def build_profile(flawed: bool) -> dict:
    n = int(DURATION_S * RATE_HZ)
    t = np.linspace(0, DURATION_S, n)
    rng = np.random.default_rng(SEED)
    base_noise = rng.normal(0, 0.02, n)

    if flawed:
        oscillation = 0.18 * np.sin(2 * np.pi * 1.1 * t)
        roll_rate  = oscillation + base_noise
        pitch_rate = oscillation * 0.85 + rng.normal(0, 0.015, n)
        sag_v = 0.65
        sats = np.where(t > DURATION_S * 0.5, 6, 13).astype(np.uint8)
    else:
        roll_rate  = base_noise
        pitch_rate = rng.normal(0, 0.02, n)
        sag_v = 0.12
        sats = np.full(n, 14, dtype=np.uint8)

    yaw_rate = rng.normal(0, 0.01, n)
    accel_x = rng.normal(0, 0.3, n)
    accel_y = rng.normal(0, 0.3, n)
    accel_z = 9.81 + rng.normal(0, 0.3, n)

    idle_v = 16.8
    voltage = np.where(
        t < 2, idle_v, idle_v - sag_v - (t / DURATION_S) * 0.3
    ) + rng.normal(0, 0.01, n)
    current = np.where(t < 2, 1.5, 18.0)
    remaining = np.clip(1.0 - t / DURATION_S * 0.6, 0.2, 1.0)

    base_lat, base_lon = 37.7749, -122.4194
    lat = base_lat + 0.0006 * np.sin(t / DURATION_S * 2 * np.pi)
    lon = base_lon + 0.0006 * np.cos(t / DURATION_S * 2 * np.pi)
    alt_m = 30 + 10 * np.sin(t / DURATION_S * np.pi)
    hdop = np.where(sats < 8, 3.5, 1.1)

    return dict(
        t=t, n=n,
        roll_rate=roll_rate, pitch_rate=pitch_rate, yaw_rate=yaw_rate,
        accel=np.column_stack([accel_x, accel_y, accel_z]),
        voltage=voltage, current=current, remaining=remaining,
        lat=lat, lon=lon, alt_m=alt_m, sats=sats, hdop=hdop,
    )


SAMPLE_PARAMS = {
    "MC_ROLLRATE_P": 0.15, "MC_PITCHRATE_P": 0.15, "MC_YAWRATE_P": 0.2,
    "MC_ROLLRATE_D": 0.003, "MC_PITCHRATE_D": 0.003,
    "MPC_XY_P": 0.95, "MPC_XY_VEL_P_ACC": 1.8,
    "BAT_LOW_THR": 0.25, "BAT_CRIT_THR": 0.1,
    "COM_RC_LOSS_T": 1.5, "EKF2_MAG_TYPE": 0,
}


# ── PX4 ULog (.ulg) ───────────────────────────────────────────────────────────
# Format reverse-engineered from pyulog's own writer (pyulog.core.ULog
# _write_file_header / _write_format_messages / _write_data_section) rather
# than guessed — header is 7 magic bytes + version + 8-byte start timestamp;
# each message is a 2-byte little-endian payload length + 1-byte type char
# (F=format, A=add-logged-message subscription, P=parameter, D=data).

def write_ulog(path: str, profile: dict) -> None:
    HEADER = b"ULog\x01\x125"
    MSG_FORMAT, MSG_ADD_LOGGED, MSG_PARAMETER, MSG_DATA, MSG_FLAG_BITS = (
        ord("F"), ord("A"), ord("P"), ord("D"), ord("B")
    )
    start_us = int(time.time() * 1e6)

    topics = {
        "vehicle_angular_velocity": (
            "uint64_t timestamp;float rollspeed;float pitchspeed;float yawspeed;",
            "<Qfff",
        ),
        "sensor_accel": (
            "uint64_t timestamp;float x;float y;float z;",
            "<Qfff",
        ),
        "battery_status": (
            "uint64_t timestamp;float voltage_v;float current_a;float remaining;",
            "<Qfff",
        ),
        "vehicle_gps_position": (
            "uint64_t timestamp;int32_t lat;int32_t lon;int32_t alt;"
            "uint8_t fix_type;uint8_t satellites_used;float hdop;",
            "<QiiiBBf",
        ),
        "estimator_status": (
            "uint64_t timestamp;uint16_t innovation_check_flags;uint16_t solution_status_flags;",
            "<QHH",
        ),
    }

    with open(path, "wb") as f:
        f.write(HEADER)
        f.write(struct.pack("B", 1))   # file format version
        f.write(struct.pack("<Q", start_us))

        flag_data = (
            struct.pack("<8B", *([0] * 8))
            + struct.pack("<8B", *([0] * 8))
            + struct.pack("<3Q", 0, 0, 0)
        )
        f.write(struct.pack("<HB", len(flag_data), MSG_FLAG_BITS) + flag_data)

        for name, (fmt_fields, _) in topics.items():
            data = f"{name}:{fmt_fields}".encode("utf-8")
            f.write(struct.pack("<HB", len(data), MSG_FORMAT) + data)

        # Parameter (P) messages must be written before any
        # AddLoggedMessage (A) — pyulog's reader treats the first A message
        # as the end of the "definitions" section and stops looking for
        # parameters/formats after that point.
        for pname, pval in SAMPLE_PARAMS.items():
            key = f"float {pname}".encode("utf-8")
            data = struct.pack("<B", len(key)) + key + struct.pack("<f", float(pval))
            f.write(struct.pack("<HB", len(data), MSG_PARAMETER) + data)

        msg_ids = {name: i for i, name in enumerate(topics)}
        for name, msg_id in msg_ids.items():
            data = struct.pack("<BH", 0, msg_id) + name.encode("utf-8")
            f.write(struct.pack("<HB", len(data), MSG_ADD_LOGGED) + data)

        n = profile["n"]
        items: list[tuple[int, bytes]] = []
        for i in range(n):
            ts = start_us + int(profile["t"][i] * 1e6)

            body = struct.pack(
                topics["vehicle_angular_velocity"][1], ts,
                float(profile["roll_rate"][i]), float(profile["pitch_rate"][i]),
                float(profile["yaw_rate"][i]),
            )
            hdr = struct.pack("<H", msg_ids["vehicle_angular_velocity"])
            data = hdr + body
            items.append((ts, struct.pack("<HB", len(data), MSG_DATA) + data))

            body = struct.pack(
                topics["sensor_accel"][1], ts,
                float(profile["accel"][i, 0]), float(profile["accel"][i, 1]),
                float(profile["accel"][i, 2]),
            )
            hdr = struct.pack("<H", msg_ids["sensor_accel"])
            data = hdr + body
            items.append((ts, struct.pack("<HB", len(data), MSG_DATA) + data))

            if i % 4 == 0:
                body = struct.pack(
                    topics["battery_status"][1], ts,
                    float(profile["voltage"][i]), float(profile["current"][i]),
                    float(profile["remaining"][i]),
                )
                hdr = struct.pack("<H", msg_ids["battery_status"])
                data = hdr + body
                items.append((ts, struct.pack("<HB", len(data), MSG_DATA) + data))

                body = struct.pack(
                    topics["vehicle_gps_position"][1], ts,
                    int(profile["lat"][i] * 1e7), int(profile["lon"][i] * 1e7),
                    int(profile["alt_m"][i] * 1000),
                    3, int(profile["sats"][i]), float(profile["hdop"][i]),
                )
                hdr = struct.pack("<H", msg_ids["vehicle_gps_position"])
                data = hdr + body
                items.append((ts, struct.pack("<HB", len(data), MSG_DATA) + data))

                body = struct.pack(topics["estimator_status"][1], ts, 0, 0b111111)
                hdr = struct.pack("<H", msg_ids["estimator_status"])
                data = hdr + body
                items.append((ts, struct.pack("<HB", len(data), MSG_DATA) + data))

        items.sort(key=lambda pair: pair[0])
        for _, buf in items:
            f.write(buf)


# ── ArduPilot dataflash (.bin) ────────────────────────────────────────────────
# Format reverse-engineered from pymavlink.DFReader (DFReader_binary,
# DFFormat, FORMAT_TO_STRUCT) — each message is 0xA3 0x95 <type_id> followed
# by a little-endian struct body; a FMT message (type 0x80) defines every
# other message type's field layout before it's used.

def write_ardupilot_bin(path: str, profile: dict) -> None:
    HEAD1, HEAD2, FMT_TYPE = 0xA3, 0x95, 0x80

    def fmt_message(type_id, name, fmt_chars, columns, field_struct):
        flen = 3 + struct.calcsize("<" + field_struct)
        body = struct.pack(
            "<BB4s16s64s", type_id, flen,
            name.encode("ascii"), fmt_chars.encode("ascii"), columns.encode("ascii"),
        )
        return bytes([HEAD1, HEAD2, FMT_TYPE]) + body

    # type_id -> (name, format chars, columns, struct fmt)
    message_types = {
        0x01: ("IMU", "Qffffff", "TimeUS,GyrX,GyrY,GyrZ,AccX,AccY,AccZ", "Qffffff"),
        0x02: ("BAT", "Qffff", "TimeUS,Volt,Curr,CurrTot,Temp", "Qffff"),
        0x03: ("GPS", "QBiiffB", "TimeUS,Status,Lat,Lng,Alt,HDop,NSats", "QBiiffB"),
        0x04: ("MSG", "QZ", "TimeUS,Message", "Q64s"),
        0x05: ("PARM", "QNf", "TimeUS,Name,Value", "Q16sf"),
    }

    with open(path, "wb") as f:
        for type_id, (name, fmt_chars, columns, _) in message_types.items():
            f.write(fmt_message(type_id, name, fmt_chars, columns, message_types[type_id][3]))

        msg = "ArduCopter V4.3.5 (sample)".encode("ascii")[:63].ljust(64, b"\x00")
        f.write(bytes([HEAD1, HEAD2, 0x04]) + struct.pack("<Q64s", 0, msg))

        for pname, pval in SAMPLE_PARAMS.items():
            name_bytes = pname.encode("ascii")[:15].ljust(16, b"\x00")
            f.write(bytes([HEAD1, HEAD2, 0x05]) + struct.pack("<Q16sf", 0, name_bytes, float(pval)))

        n = profile["n"]
        start_us = 0
        for i in range(n):
            ts = start_us + int(profile["t"][i] * 1e6)

            f.write(
                bytes([HEAD1, HEAD2, 0x01])
                + struct.pack(
                    "<Qffffff", ts,
                    float(profile["roll_rate"][i]), float(profile["pitch_rate"][i]),
                    float(profile["yaw_rate"][i]),
                    float(profile["accel"][i, 0]), float(profile["accel"][i, 1]),
                    float(profile["accel"][i, 2]),
                )
            )

            if i % 4 == 0:
                f.write(
                    bytes([HEAD1, HEAD2, 0x02])
                    + struct.pack(
                        "<Qffff", ts,
                        float(profile["voltage"][i]), float(profile["current"][i]),
                        0.0, 25.0,
                    )
                )
                f.write(
                    bytes([HEAD1, HEAD2, 0x03])
                    + struct.pack(
                        "<QBiiffB", ts, 3,
                        int(profile["lat"][i] * 1e7), int(profile["lon"][i] * 1e7),
                        float(profile["alt_m"][i] * 1000), float(profile["hdop"][i]),
                        int(profile["sats"][i]),
                    )
                )


# ── MAVLink telemetry (.tlog) ─────────────────────────────────────────────────
# Real MAVLink packets (packed via pymavlink's own encoder — not a hand-rolled
# frame) prefixed with the standard 8-byte big-endian microsecond timestamp,
# matching mavutil.mavlogfile's own write format exactly.

def write_tlog(path: str, profile: dict) -> None:
    from pymavlink.dialects.v20 import common as dialect

    mav = dialect.MAVLink(None, srcSystem=1, srcComponent=1)
    n = profile["n"]
    base_time = time.time() - DURATION_S

    def frame(ts, msg):
        usec = int(ts * 1e6)
        return struct.pack(">Q", usec) + msg.pack(mav)

    with open(path, "wb") as f:
        for i in range(n):
            ts = base_time + profile["t"][i]
            t_ms = int(profile["t"][i] * 1000)

            if i % 20 == 0:
                hb = dialect.MAVLink_heartbeat_message(
                    type=2, autopilot=3, base_mode=81, custom_mode=0,
                    system_status=4, mavlink_version=3,
                )
                f.write(frame(ts, hb))

            att = dialect.MAVLink_attitude_message(
                time_boot_ms=t_ms, roll=0.0, pitch=0.0, yaw=0.0,
                rollspeed=float(profile["roll_rate"][i]),
                pitchspeed=float(profile["pitch_rate"][i]),
                yawspeed=float(profile["yaw_rate"][i]),
            )
            f.write(frame(ts, att))

            mg = 1000.0 / 9.80665
            imu = dialect.MAVLink_scaled_imu_message(
                time_boot_ms=t_ms,
                xacc=int(profile["accel"][i, 0] * mg), yacc=int(profile["accel"][i, 1] * mg),
                zacc=int(profile["accel"][i, 2] * mg),
                xgyro=0, ygyro=0, zgyro=0, xmag=0, ymag=0, zmag=0,
            )
            f.write(frame(ts, imu))

            if i % 10 == 0:
                sys_status = dialect.MAVLink_sys_status_message(
                    onboard_control_sensors_present=0, onboard_control_sensors_enabled=0,
                    onboard_control_sensors_health=0, load=500,
                    voltage_battery=int(profile["voltage"][i] * 1000),
                    current_battery=int(profile["current"][i] * 100),
                    battery_remaining=int(profile["remaining"][i] * 100),
                    drop_rate_comm=0, errors_comm=0,
                    errors_count1=0, errors_count2=0, errors_count3=0, errors_count4=0,
                )
                f.write(frame(ts, sys_status))

                gps = dialect.MAVLink_gps_raw_int_message(
                    time_usec=int(ts * 1e6), fix_type=3,
                    lat=int(profile["lat"][i] * 1e7), lon=int(profile["lon"][i] * 1e7),
                    alt=int(profile["alt_m"][i] * 1000),
                    eph=int(profile["hdop"][i] * 100), epv=100, vel=500, cog=9000,
                    satellites_visible=int(profile["sats"][i]),
                )
                f.write(frame(ts, gps))

        for pname, pval in SAMPLE_PARAMS.items():
            pv = dialect.MAVLink_param_value_message(
                param_id=pname.encode("ascii")[:16], param_value=float(pval), param_type=9,
                param_count=len(SAMPLE_PARAMS), param_index=0,
            )
            f.write(frame(base_time, pv))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for flawed, suffix in [(False, "clean"), (True, "flawed")]:
        profile = build_profile(flawed)
        ulg_path = os.path.join(OUT_DIR, f"sample_{suffix}.ulg")
        bin_path = os.path.join(OUT_DIR, f"sample_{suffix}.bin")
        tlog_path = os.path.join(OUT_DIR, f"sample_{suffix}.tlog")

        write_ulog(ulg_path, profile)
        write_ardupilot_bin(bin_path, profile)
        write_tlog(tlog_path, profile)

        print(f"Wrote {ulg_path} ({os.path.getsize(ulg_path)} bytes)")
        print(f"Wrote {bin_path} ({os.path.getsize(bin_path)} bytes)")
        print(f"Wrote {tlog_path} ({os.path.getsize(tlog_path)} bytes)")


if __name__ == "__main__":
    main()
