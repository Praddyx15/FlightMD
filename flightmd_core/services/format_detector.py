"""
Works out which log format a file is, from its first bytes:

  "px4_ulog"       PX4 ULog (.ulg)
  "ardupilot_bin"  ArduPilot dataflash (.bin)
  "mavlink_tlog"   MAVLink telemetry log written by QGC / Mission Planner (.tlog)

The extension is never trusted on its own; anything that doesn't match is rejected.
"""

import os

ULOG_MAGIC = b"ULog\x01\x12\x35"

# every dataflash log opens with a FMT message (type 0x80)
DATAFLASH_HEAD = b"\xA3\x95"
DATAFLASH_FMT = 0x80

MAVLINK_V1_STX = 0xFE
MAVLINK_V2_STX = 0xFD

# how many back-to-back tlog records have to parse before we believe it
TLOG_FRAMES_NEEDED = 3

# enough for TLOG_FRAMES_NEEDED max-size v2 frames with signatues
HEADER_BYTES = 4096

SUPPORTED_EXTENSIONS = {".ulg", ".ulog", ".bin", ".tlog", ".log"}


class UnsupportedFormatError(ValueError):
    pass


def _tlog_frame_len(buf: bytes, pos: int):
    """Length of the timestamp + MAVLink frame starting at pos, or None if it isn't one.
    Returns -1 when buf ends before the frame does."""
    if pos + 8 >= len(buf):
        return -1
    # timestamp is big-endian usec; anything with a non-zero top byte is past year 2280
    if buf[pos] != 0:
        return None
    stx = buf[pos + 8]
    if stx == MAVLINK_V1_STX:
        if pos + 9 >= len(buf):
            return -1
        n = 8 + 6 + buf[pos + 9] + 2
    elif stx == MAVLINK_V2_STX:
        if pos + 10 >= len(buf):
            return -1
        incompat = buf[pos + 10]
        if incompat & ~0x01:
            return None
        n = 8 + 10 + buf[pos + 9] + 2 + (13 if incompat & 0x01 else 0)
    else:
        return None
    return n if pos + n <= len(buf) else -1


def _check_tlog(buf: bytes, complete: bool):
    """True if buf starts with TLOG_FRAMES_NEEDED valid tlog records (or is a whole tiny
    tlog made of complete records), False if it isn't a tlog, None if buf is too short to tell."""
    pos = frames = 0
    while frames < TLOG_FRAMES_NEEDED:
        if complete and frames and pos == len(buf):
            return True
        n = _tlog_frame_len(buf, pos)
        if n is None:
            return False
        if n == -1:
            return None
        pos += n
        frames += 1
    return True


def _check_dataflash(buf: bytes) -> bool:
    if buf[:2] != DATAFLASH_HEAD or len(buf) < 3 or buf[2] != DATAFLASH_FMT:
        return False
    # FMT body: type, length, 4-char name. The name is upper-case ASCII, nul padded.
    name = buf[5:9]
    return all(c == 0 or 48 <= c <= 57 or 65 <= c <= 90 for c in name)


def detect_format_from_header(header: bytes, filename: str = "", complete: bool = False) -> str:
    """
    Identify a log format from its first bytes (pass HEADER_BYTES of them). Doesn't touch
    disk, so it works on an upload still in memory.

    A short header that could be the start of a .tlog is accepted provisionally when the
    name ends in .tlog; detect_format() re-checks the file on disk. complete=True means
    header is the whole file.

    Raises UnsupportedFormatError if the format can't be determined.
    """
    ext = os.path.splitext(filename)[1].lower()

    if header[:7] == ULOG_MAGIC:
        return "px4_ulog"

    if _check_dataflash(header):
        return "ardupilot_bin"

    tlog = _check_tlog(header, complete)
    if tlog:
        return "mavlink_tlog"
    if tlog is None and not complete and ext == ".tlog" and header[:1] == b"\x00":
        return "mavlink_tlog"

    if ext == ".log":
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
    """Inspect a log on disk and return its format name. Raises UnsupportedFormatError."""
    with open(file_path, "rb") as f:
        header = f.read(HEADER_BYTES)
    complete = len(header) < HEADER_BYTES
    return detect_format_from_header(header, os.path.basename(file_path), complete=complete)
