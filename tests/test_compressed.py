import gzip
import io
import os
import zipfile

import pytest

from flightmd_core.services import compressed
from flightmd_core.services.compressed import open_log

LOG = b"ULog\x01\x12\x35\x01" + bytes(range(256)) * 40
MB = 1 << 20


def make_zip(path, entries, method=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression=method) as z:
        for name, data in entries:
            z.writestr(name, data)
    return str(path)


@pytest.fixture
def tmpdirs(tmp_path, monkeypatch):
    """Point mkdtemp at tmp_path so the tests can see what's left behind."""
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setattr(compressed.tempfile, "tempdir", str(root))
    return root


def test_plain_log_is_returned_as_is(tmp_path, tmpdirs):
    p = tmp_path / "flight.ulg"
    p.write_bytes(LOG)
    path, cleanup = open_log(str(p), 10 * MB)
    assert path == str(p)
    cleanup()
    assert p.exists()
    assert list(tmpdirs.iterdir()) == []


def test_gzip(tmp_path, tmpdirs):
    p = tmp_path / "flight.ulg.gz"
    p.write_bytes(gzip.compress(LOG))
    path, cleanup = open_log(str(p), 10 * MB)
    assert path.endswith(".ulg")
    with open(path, "rb") as f:
        assert f.read() == LOG
    cleanup()
    assert not os.path.exists(path)
    assert list(tmpdirs.iterdir()) == []


def test_gzip_detected_by_content_not_name(tmp_path, tmpdirs):
    p = tmp_path / "upload.bin"
    p.write_bytes(gzip.compress(LOG))
    path, cleanup = open_log(str(p), 10 * MB)
    with open(path, "rb") as f:
        assert f.read() == LOG
    cleanup()


def test_zip_with_one_log(tmp_path, tmpdirs):
    z = make_zip(tmp_path / "logs.zip", [("2026-05-01/flight.bin", LOG)])
    path, cleanup = open_log(z, 10 * MB)
    assert path.endswith(".bin")
    with open(path, "rb") as f:
        assert f.read() == LOG
    cleanup()
    assert list(tmpdirs.iterdir()) == []


def test_zip_ignores_os_clutter_and_folders(tmp_path, tmpdirs):
    z = make_zip(tmp_path / "logs.zip", [
        ("logs/", b""),
        ("logs/flight.tlog", LOG),
        ("__MACOSX/logs/._flight.tlog", b"\x00\x05\x16\x07"),
        ("logs/.DS_Store", b"junk"),
        ("Thumbs.db", b"junk"),
    ])
    path, cleanup = open_log(z, 10 * MB)
    assert path.endswith(".tlog")
    cleanup()


def test_stored_zip(tmp_path, tmpdirs):
    z = make_zip(tmp_path / "logs.zip", [("a.ulg", LOG)], method=zipfile.ZIP_STORED)
    path, cleanup = open_log(z, 10 * MB)
    with open(path, "rb") as f:
        assert f.read() == LOG
    cleanup()


@pytest.mark.parametrize("entries", [
    [],
    [("a.ulg", LOG), ("b.ulg", LOG)],
    [("a.ulg", LOG), ("notes.txt", b"flew well")],
])
def test_zip_needs_exactly_one_file(tmp_path, tmpdirs, entries):
    z = make_zip(tmp_path / "logs.zip", entries)
    with pytest.raises(ValueError, match="exactly one"):
        open_log(z, 10 * MB)
    assert list(tmpdirs.iterdir()) == []


@pytest.mark.parametrize("name", ["../flight.ulg", "logs/../../flight.ulg", "/etc/flight.ulg", "C:/flight.ulg", "..\\flight.ulg"])
def test_zip_path_traversal_is_refused(tmp_path, tmpdirs, name):
    z = make_zip(tmp_path / "logs.zip", [(name, LOG)])
    with pytest.raises(ValueError, match="unsafe path"):
        open_log(z, 10 * MB)
    assert list(tmpdirs.iterdir()) == []


def test_zip_bomb_by_declared_ratio(tmp_path, tmpdirs):
    z = make_zip(tmp_path / "bomb.zip", [("flight.ulg", b"\x00" * (8 * MB))])
    assert os.path.getsize(z) < 64 * 1024
    with pytest.raises(ValueError, match="expands far more"):
        open_log(z, 512 * MB)
    assert list(tmpdirs.iterdir()) == []


def test_zip_with_lying_header_stops_at_the_ratio_cap(tmp_path, tmpdirs, monkeypatch):
    # header checks pass when the sizes in the central directory lie; the stream cap still holds
    z = make_zip(tmp_path / "bomb.zip", [("flight.ulg", b"\x00" * (8 * MB))])
    monkeypatch.setattr(compressed, "MAX_RATIO", 10**9)
    real = compressed._copy_capped

    def strict(opener, out, max_bytes, packed_size):
        monkeypatch.setattr(compressed, "MAX_RATIO", 200)
        return real(opener, out, max_bytes, packed_size)

    monkeypatch.setattr(compressed, "_copy_capped", strict)
    with pytest.raises(ValueError, match="expands far more"):
        open_log(z, 512 * MB)
    assert list(tmpdirs.iterdir()) == []


def test_gzip_bomb(tmp_path, tmpdirs):
    p = tmp_path / "bomb.ulg.gz"
    p.write_bytes(gzip.compress(b"\x00" * (16 * MB)))
    with pytest.raises(ValueError, match="expands far more"):
        open_log(str(p), 512 * MB)
    assert list(tmpdirs.iterdir()) == []


def test_over_the_size_cap(tmp_path, tmpdirs):
    data = os.urandom(3 * MB)   # incompressible, so the ratio check doesn't fire first
    p = tmp_path / "big.ulg.gz"
    p.write_bytes(gzip.compress(data))
    with pytest.raises(ValueError, match="limit"):
        open_log(str(p), 2 * MB)
    z = make_zip(tmp_path / "big.zip", [("big.ulg", data)])
    with pytest.raises(ValueError, match="limit"):
        open_log(z, 2 * MB)
    assert list(tmpdirs.iterdir()) == []


@pytest.mark.parametrize("inner", ["flight.ulg.gz", "more.zip"])
def test_nested_archive_by_name(tmp_path, tmpdirs, inner):
    z = make_zip(tmp_path / "logs.zip", [(inner, gzip.compress(LOG))])
    with pytest.raises(ValueError, match="another archive"):
        open_log(z, 10 * MB)


def test_nested_archive_by_content(tmp_path, tmpdirs):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("flight.ulg", LOG)
    p = tmp_path / "flight.ulg.gz"
    p.write_bytes(gzip.compress(inner.getvalue()))
    with pytest.raises(ValueError, match="another archive"):
        open_log(str(p), 10 * MB)
    assert list(tmpdirs.iterdir()) == []


def test_truncated_gzip(tmp_path, tmpdirs):
    p = tmp_path / "cut.ulg.gz"
    p.write_bytes(gzip.compress(LOG)[:-30])
    with pytest.raises(ValueError, match="damaged"):
        open_log(str(p), 10 * MB)
    assert list(tmpdirs.iterdir()) == []


def test_corrupt_zip(tmp_path, tmpdirs):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    with pytest.raises(ValueError, match="damaged"):
        open_log(str(p), 10 * MB)
