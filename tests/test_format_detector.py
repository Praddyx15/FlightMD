"""
Tests for format_detector — magic-byte and extension-based format detection.
"""

import pytest

from flightmd_core.services.format_detector import (
    detect_format_from_header,
    UnsupportedFormatError,
)


def test_px4_ulog_magic_detected():
    header = b"\x55\x4C\x6F\x67\x01\x00\x00\x00"
    assert detect_format_from_header(header, "flight.ulg") == "px4_ulog"


def test_px4_ulog_magic_detected_regardless_of_extension():
    # Magic bytes are authoritative even with an unrelated filename.
    header = b"\x55\x4C\x6F\x67\x01\x00\x00\x00"
    assert detect_format_from_header(header, "weird_name.dat") == "px4_ulog"


def test_ardupilot_bin_magic_detected():
    header = b"\xA3\x95\x00\x00\x00\x00\x00\x00"
    assert detect_format_from_header(header, "flight.bin") == "ardupilot_bin"


def test_mavlink_v2_stx_detected():
    header = bytes([0xFD, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01])
    assert detect_format_from_header(header, "flight.tlog") == "mavlink_tlog"


def test_mavlink_v1_stx_detected():
    header = bytes([0xFE, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01])
    assert detect_format_from_header(header, "flight.tlog") == "mavlink_tlog"


def test_tlog_extension_fallback_when_stx_not_first_byte():
    # .tlog has no fixed file-level magic; the extension is trusted as a
    # last resort (the disk-backed detect_format() additionally verifies
    # the file actually parses as MAVLink before trusting this).
    header = b"\x00\x01\x02\x03\x04\x05\x06\x07"
    assert detect_format_from_header(header, "flight.tlog") == "mavlink_tlog"


def test_garbage_content_with_ulg_extension_is_rejected():
    """
    A file merely named "*.ulg" with unrelated content must be rejected —
    the extension is not trusted for formats that have a real magic byte
    signature. This guards against silently mis-parsing garbage as PX4 data.
    """
    header = b"\x00\x01\x02\x03\x00\x00\x00\x00"
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(header, "bad.ulg")


def test_garbage_content_with_bin_extension_is_rejected():
    header = b"\x00\x01\x02\x03\x00\x00\x00\x00"
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(header, "bad.bin")


def test_text_log_extension_rejected_with_helpful_message():
    header = b"not a binary log at all "
    with pytest.raises(UnsupportedFormatError, match="text-format"):
        detect_format_from_header(header, "mission_planner_export.log")


def test_unrecognized_format_rejected():
    header = b"random bytes"
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(header, "flight.xyz")
