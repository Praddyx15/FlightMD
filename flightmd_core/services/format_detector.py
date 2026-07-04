"""
format_detector — identifies which flight-log format a file is, so the
orchestrator can dispatch to the correct parser.

Supported formats:
  "px4_ulog"       — PX4 ULog (.ulg / .ulog)
  "ardupilot_bin"  — ArduPilot dataflash log (.bin)
  "mavlink_tlog"   — MAVLink telemetry log, produced by QGroundControl or
                     Mission Planner during a GCS-connected flight (.tlog)
"""

import os

# PX4 ULog magic bytes: "ULog" = 0x55 0x4C 0x6F 0x67
ULOG_MAGIC = b"\x55\x4C\x6F\x67"

# ArduPilot dataflash (.bin) messages start with a fixed 2-byte header
ARDUPILOT_BIN_MAGIC = b"\xA3\x95"

# MAVLink packet start-of-frame bytes (v1 = 0xFE, v2 = 0xFD). .tlog files are
# a raw stream of these packets with no file-level magic/header.
MAVLINK_V1_STX = 0xFE
MAVLINK_V2_STX = 0xFD

SUPPORTED_EXTENSIONS = {".ulg", ".ulog", ".bin", ".tlog", ".log"}


class UnsupportedFormatError(ValueError):
    pass


def detect_format_from_header(header: bytes, filename: str = "") -> str:
    """
    Identify a log format from its first few bytes. Does not touch disk —
    safe to call on an in-memory upload before anything is written to a
    temp file.

    The filename extension is used only as a fallback for formats that have
    no fixed file-level magic (.tlog is a raw MAVLink packet stream, and its
    first byte is only usually — not always — a MAVLink start-of-frame
    byte). For .ulg/.ulog/.bin, correctness requires the actual magic bytes
    to match — a file merely *named* "flight.ulg" with unrelated content is
    rejected rather than trusted, exactly as it was before format detection
    was extended beyond PX4-only.

    Raises UnsupportedFormatError if the format cannot be determined.
    """
    ext = os.path.splitext(filename)[1].lower()

    if header[:4] == ULOG_MAGIC:
        return "px4_ulog"

    if header[:2] == ARDUPILOT_BIN_MAGIC:
        return "ardupilot_bin"

    if len(header) > 0 and header[0] in (MAVLINK_V1_STX, MAVLINK_V2_STX):
        return "mavlink_tlog"

    if ext == ".tlog":
        # No fixed magic exists for this format at all — the extension is
        # the only signal available at this stage. detect_format() (the
        # disk-backed path) additionally verifies the file actually parses
        # as a MAVLink stream before trusting this.
        return "mavlink_tlog"

    if ext == ".log":
        # ArduPilot also produces text-format .log files from Mission
        # Planner exports; these are not binary dataflash logs and are not
        # yet supported for parsing.
        raise UnsupportedFormatError(
            "'.log' text-format exports are not yet supported. Upload the "
            "original .bin (ArduPilot), .ulg (PX4), or .tlog (MAVLink "
            "telemetry) log instead."
        )

    raise UnsupportedFormatError(
        f"Unrecognized log format{f' ({filename})' if filename else ''}. "
        f"Supported: PX4 ULog (.ulg), ArduPilot dataflash (.bin), "
        f"MAVLink telemetry (.tlog)."
    )


def detect_format(file_path: str) -> str:
    """
    Inspect a log file on disk and return one of "px4_ulog",
    "ardupilot_bin", or "mavlink_tlog". Raises UnsupportedFormatError if the
    format cannot be determined.
    """
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        header = f.read(8)

    fmt = detect_format_from_header(header, filename)

    if fmt == "mavlink_tlog" and not _looks_like_mavlink_stream(file_path):
        raise UnsupportedFormatError(
            f"File appears to be a .tlog but does not contain a valid "
            f"MAVLink stream: {file_path}"
        )

    return fmt


def _looks_like_mavlink_stream(file_path: str) -> bool:
    """
    Best-effort check that a .tlog file actually contains parseable MAVLink
    packets, by attempting to read one message.
    """
    try:
        from pymavlink import mavutil
    except ImportError:
        # pymavlink not installed — trust the header/extension rather than fail
        return True

    try:
        conn = mavutil.mavlink_connection(file_path, robust_parsing=True)
        try:
            conn.recv_match(blocking=False)
            # An empty/near-empty file may legitimately return None on the
            # first read without being invalid; only fail on a parse error.
            return True
        finally:
            conn.close()
    except Exception:
        return False
