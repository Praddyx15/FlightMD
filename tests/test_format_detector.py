import struct

import pytest

from flightmd_core.services.format_detector import (
    detect_format,
    detect_format_from_header,
    UnsupportedFormatError,
)

ULOG_HEADER = b"ULog\x01\x12\x35\x01" + struct.pack("<Q", 123456)
DATAFLASH_HEADER = b"\xA3\x95\x80\x80\x59FMT\x00"


def tlog_record(ts_us=1_700_000_000_000_000, payload=b"\x00" * 9, msgid=0, v2=True):
    if v2:
        frame = bytes([0xFD, len(payload), 0, 0, 0, 1, 1]) + msgid.to_bytes(3, "little") + payload + b"\x00\x00"
    else:
        frame = bytes([0xFE, len(payload), 0, 1, 1, msgid]) + payload + b"\x00\x00"
    return struct.pack(">Q", ts_us) + frame


def test_px4_ulog_magic_detected():
    assert detect_format_from_header(ULOG_HEADER, "flight.ulg") == "px4_ulog"


def test_px4_ulog_magic_detected_regardless_of_extension():
    assert detect_format_from_header(ULOG_HEADER, "weird_name.dat") == "px4_ulog"


def test_ulog_needs_the_full_magic():
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(b"ULog\x01\x00\x00\x00", "flight.ulg")


def test_ardupilot_bin_detected():
    assert detect_format_from_header(DATAFLASH_HEADER, "flight.bin") == "ardupilot_bin"


def test_dataflash_head_without_fmt_rejected():
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(b"\xA3\x95\x01\x00\x00\x00\x00\x00", "flight.bin")


@pytest.mark.parametrize("v2", [True, False])
def test_tlog_detected_from_frames(v2):
    data = b"".join(tlog_record(1_700_000_000_000_000 + i, v2=v2) for i in range(3))
    assert detect_format_from_header(data, "anything.dat", complete=True) == "mavlink_tlog"


def test_signed_v2_frames_detected():
    rec = tlog_record()
    signed = rec[:10] + b"\x01" + rec[11:] + b"\x00" * 13  # incompat flag 1 = 13-byte signature
    assert detect_format_from_header(signed * 3, "flight.tlog", complete=True) == "mavlink_tlog"


def test_tiny_complete_tlog_detected():
    assert detect_format_from_header(tlog_record(), "flight.tlog", complete=True) == "mavlink_tlog"


def test_stx_without_timestamp_is_not_a_tlog():
    # what the old detector accepted: a raw MAVLink stream / anything starting 0xFD
    data = bytes([0xFD, 0x09, 0x00, 0x00, 0x00, 0x01, 0x01, 0x00]) * 100
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(data, "flight.tlog", complete=True)


@pytest.mark.parametrize("encoding", ["utf-16-be", "utf-16-le"])
def test_utf16_text_rejected(encoding):
    data = "﻿just some notes, not a log\n".encode(encoding) * 50
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(data, "flight.tlog", complete=True)


def test_garbage_named_tlog_rejected():
    data = bytes(range(256)) * 20
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(data, "flight.tlog", complete=True)


def test_truncated_tlog_rejected():
    data = tlog_record() + tlog_record()[:12]
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(data, "flight.tlog", complete=True)


def test_short_tlog_header_accepted_provisionally():
    # the upload route only has a few bytes; detect_format() re-checks on disk
    assert detect_format_from_header(tlog_record()[:8], "flight.tlog") == "mavlink_tlog"


def test_short_tlog_header_needs_the_extension():
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(tlog_record()[:8], "flight.bin")


@pytest.mark.parametrize("data", [b"", b"U", b"ULo", b"\xA3"])
def test_truncated_input_rejected(data):
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(data, "flight.ulg", complete=True)


def test_garbage_content_with_ulg_extension_is_rejected():
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(b"\x00\x01\x02\x03\x00\x00\x00\x00", "bad.ulg")


def test_garbage_content_with_bin_extension_is_rejected():
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(b"\x00\x01\x02\x03\x00\x00\x00\x00", "bad.bin")


def test_text_log_extension_rejected_with_helpful_message():
    with pytest.raises(UnsupportedFormatError, match="text-format"):
        detect_format_from_header(b"not a binary log at all ", "mission_planner_export.log")


def test_unrecognized_format_rejected():
    with pytest.raises(UnsupportedFormatError):
        detect_format_from_header(b"random bytes", "flight.xyz")


def test_detect_format_on_disk(tmp_path):
    good = tmp_path / "a.tlog"
    good.write_bytes(b"".join(tlog_record(1_700_000_000_000_000 + i * 1000) for i in range(50)))
    assert detect_format(str(good)) == "mavlink_tlog"

    bad = tmp_path / "b.tlog"
    bad.write_bytes(tlog_record()[:8] + b"\x00" * 100)
    with pytest.raises(UnsupportedFormatError):
        detect_format(str(bad))
