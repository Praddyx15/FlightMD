"""
Works out which log format a file is, from its first bytes:

  "px4_ulog"        PX4 ULog (.ulg)
  "ardupilot_bin"   ArduPilot dataflash (.bin)
  "ardupilot_log"   ArduPilot dataflash as text (.log, "FMT, 128, 89, ..." lines)
  "mavlink_tlog"    MAVLink telemetry log written by QGC / Mission Planner (.tlog)
  "betaflight_bbl"  Betaflight / INAV blackbox (.bbl, .bfl, LOGxxx.TXT)
  "dji_txt"         DJI app flight record (DJIFlightRecord_*.txt)
  "dji_dat"         DJI aircraft .DAT: recognised, but refused with an explanation

The extension is never trusted on its own; anything that doesn't match is rejected.
.gz / .zip uploads are unpacked first (compressed.open_log), so they never get here.
PARSERS maps every id to its parser class.
"""

import os
import re

from flightmd_core.services.ardupilot_parser import ArduPilotBinParser
from flightmd_core.services.ardupilot_text_parser import ArduPilotTextParser
from flightmd_core.services.betaflight_parser import BetaflightParser, looks_like_blackbox
from flightmd_core.services.dji_parser import DAT_UNSUPPORTED, DJIParser, check_dji_txt, looks_like_dji_dat
from flightmd_core.services.mavlink_telemetry_parser import MavlinkTelemetryParser
from flightmd_core.services.ulog_parser import ULogParser

ULOG_MAGIC = b"ULog\x01\x12\x35"

# every dataflash log opens with a FMT message (type 0x80)
DATAFLASH_HEAD = b"\xA3\x95"
DATAFLASH_FMT = 0x80

# first line of a text dataflash log: FMT, <type>, <length>, <name>, <format>, <columns>
TEXT_DATAFLASH_FMT = re.compile(rb"FMT, ?\d+, ?\d+, ?\w+, ?\w+, ?\w")

MAVLINK_V1_STX = 0xFE
MAVLINK_V2_STX = 0xFD

# how many back-to-back tlog records have to parse before we believe it
TLOG_FRAMES_NEEDED = 3

# enough for TLOG_FRAMES_NEEDED max-size v2 frames with signatues
HEADER_BYTES = 4096

SUPPORTED_EXTENSIONS = {".ulg", ".ulog", ".bin", ".tlog", ".log", ".bbl", ".bfl", ".txt"}

PARSERS: dict[str, type] = {
    "px4_ulog": ULogParser,
    "ardupilot_bin": ArduPilotBinParser,
    "ardupilot_log": ArduPilotTextParser,
    "mavlink_tlog": MavlinkTelemetryParser,
    "betaflight_bbl": BetaflightParser,
    "dji_txt": DJIParser,
    # the detector refuses .DAT before parsing; DJIParser refuses it too if it ever gets one
    "dji_dat": DJIParser,
}


class UnsupportedFormatError(ValueError):
    def __init__(self, message: str, format_id: str | None = None):
        super().__init__(message)
        # set when the format was recognised but can't be analysed (dji_dat)
        self.format_id = format_id


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


def _check_text_dataflash(buf: bytes) -> bool:
    if b"\x00" in buf:
        return False
    # Mission Planner exports sometimes start with a blank line or a BOM
    text = buf.removeprefix(b"\xef\xbb\xbf").lstrip(b"\r\n\t ")
    return TEXT_DATAFLASH_FMT.match(text) is not None


def detect_format_from_header(header: bytes, filename: str = "", complete: bool = False) -> str:
    """
    Identify a log format from its first bytes (pass HEADER_BYTES of them). Doesn't touch
    disk, so it works on an upload still in memory.

    A short header that could be the start of a .tlog (or a DJI .txt) is accepted
    provisionally when the name has that extension; detect_format() re-checks the file
    on disk. complete=True means header is the whole file.

    Raises UnsupportedFormatError if the format can't be determined, or for a DJI .DAT,
    which is recognised but not supported (format_id="dji_dat").
    """
    ext = os.path.splitext(filename)[1].lower()

    if header[:7] == ULOG_MAGIC:
        return "px4_ulog"

    if _check_dataflash(header):
        return "ardupilot_bin"

    if looks_like_blackbox(header):
        return "betaflight_bbl"

    if _check_text_dataflash(header):
        return "ardupilot_log"

    if looks_like_dji_dat(header):
        raise UnsupportedFormatError(DAT_UNSUPPORTED, format_id="dji_dat")

    tlog = _check_tlog(header, complete)
    if tlog:
        return "mavlink_tlog"
    if tlog is None and not complete and ext == ".tlog" and header[:1] == b"\x00":
        return "mavlink_tlog"

    dji = check_dji_txt(header, complete)
    if dji or (dji is None and not complete and ext == ".txt"):
        return "dji_txt"

    if ext == ".log":
        raise UnsupportedFormatError(
            "This '.log' file isn't an ArduPilot text-format dataflash log (those start "
            "with 'FMT, ...' lines). Upload the original .bin (ArduPilot), .ulg (PX4), "
            "or .tlog (MAVLink telemetry) log instead."
        )

    raise UnsupportedFormatError(
        f"Unrecognized log format{f' ({filename})' if filename else ''}. "
        f"Supported: PX4 ULog (.ulg), ArduPilot dataflash (.bin or text .log), "
        f"MAVLink telemetry (.tlog), Betaflight/INAV blackbox (.bbl/.bfl) and DJI "
        f"flight records (.txt), also inside a .gz or .zip."
    )


def detect_format(file_path: str) -> str:
    """Inspect a log on disk and return its format name. Raises UnsupportedFormatError."""
    with open(file_path, "rb") as f:
        header = f.read(HEADER_BYTES)
    complete = len(header) < HEADER_BYTES
    return detect_format_from_header(header, os.path.basename(file_path), complete=complete)
