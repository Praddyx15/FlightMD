"""
Opens .gz and .zip uploads so the format detector sees the log inside.

open_log(path, max_bytes) returns (path to the log, cleanup). A plain log comes back
as-is with a no-op cleanup; an archive is decompressed into a private temp directory
that cleanup() removes. The output is streamed with a hard byte cap and a
compression-ratio cap, so a zip bomb stops after a few MB of disk writes instead of
filling it. A zip must hold exactly one file (OS clutter like __MACOSX/ is ignored);
nested archives and entry names that try to leave the directory are refused.
"""

import gzip
import os
import re
import shutil
import tempfile
import zipfile
import zlib
from typing import Callable

GZIP_MAGIC = b"\x1f\x8b"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")
# what's inside must not be another archive (gzip, zip, bzip2, xz, 7z, rar)
ARCHIVE_MAGICS = (GZIP_MAGIC, b"PK\x03\x04", b"PK\x05\x06", b"BZh", b"\xfd7zXZ\x00", b"7z\xbc\xaf\x27\x1c", b"Rar!")

# Real logs compress 3-20x (text dataflash logs the most). 200x only happens on
# padding or a crafted file.
MAX_RATIO = 200
# below this the ratio isn't checked; tiny test logs full of zeros compress absurdly well
RATIO_FLOOR_BYTES = 1 << 20
CHUNK = 1 << 16

_JUNK = re.compile(r"(^|/)(__MACOSX/|\.DS_Store$|Thumbs\.db$|desktop\.ini$)", re.I)


def _noop() -> None:
    pass


def open_log(path: str, max_bytes: int) -> tuple[str, Callable[[], None]]:
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith(GZIP_MAGIC):
        opener, inner = _gzip_source(path)
    elif head.startswith(ZIP_MAGICS):
        opener, inner = _zip_source(path, max_bytes)
    else:
        return path, _noop

    tmpdir = tempfile.mkdtemp(prefix="flightmd-")

    def cleanup() -> None:
        shutil.rmtree(tmpdir, ignore_errors=True)

    out = os.path.join(tmpdir, "log" + _extension(inner))
    try:
        _copy_capped(opener, out, max_bytes, os.path.getsize(path))
        with open(out, "rb") as f:
            if f.read(8).startswith(ARCHIVE_MAGICS):
                raise ValueError("The archive contains another archive; upload the log itself or a single .gz/.zip.")
    except BaseException:
        cleanup()
        raise
    return out, cleanup


def _gzip_source(path: str):
    # .ulg.gz -> .ulg; the detector only uses the extension for messages and .tlog hints
    inner = os.path.basename(path)
    if inner.lower().endswith(".gz"):
        inner = inner[:-3]
    return (lambda: gzip.open(path, "rb")), inner


def _zip_source(path: str, max_bytes: int):
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"The zip file is damaged: {e}") from None
    with zf:
        files = []
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if _unsafe_name(name):
                raise ValueError(f"The zip has an entry with an unsafe path ({info.filename!r}).")
            if info.is_dir() or _JUNK.search(name):
                continue
            files.append(info)

    if len(files) != 1:
        raise ValueError(f"A zip upload must contain exactly one log file; this one has {len(files)}.")
    info = files[0]
    if info.flag_bits & 0x1:
        raise ValueError("The zip is password protected.")
    if info.file_size > max_bytes:
        raise ValueError(f"The log in the zip is {info.file_size / 1e6:.0f} MB; the limit is {max_bytes / 1e6:.0f} MB.")
    if info.file_size > RATIO_FLOOR_BYTES and info.file_size > MAX_RATIO * max(info.compress_size, 1):
        raise ValueError("The zip expands far more than a flight log can; refusing it.")
    if os.path.splitext(info.filename)[1].lower() in (".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".bz2", ".xz"):
        raise ValueError("The zip contains another archive; upload the log itself or a single .gz/.zip.")

    def opener():
        zf = zipfile.ZipFile(path)
        return _ClosingMember(zf, zf.open(info))

    return opener, info.filename.replace("\\", "/").rsplit("/", 1)[-1]


class _ClosingMember:
    """The member stream, plus closing the ZipFile it came from."""

    def __init__(self, zf, member):
        self.zf, self.member = zf, member

    def read(self, n):
        return self.member.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.member.close()
        self.zf.close()


def _unsafe_name(name: str) -> bool:
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return True
    return ".." in name.split("/")


def _extension(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else ""


def _copy_capped(opener, out: str, max_bytes: int, packed_size: int) -> None:
    limit = min(max_bytes, max(MAX_RATIO * packed_size, RATIO_FLOOR_BYTES))
    written = 0
    try:
        with opener() as src, open(out, "wb") as dst:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    if written > max_bytes:
                        raise ValueError(f"The decompressed log is over the {max_bytes / 1e6:.0f} MB limit.")
                    raise ValueError("The archive expands far more than a flight log can; refusing it.")
                dst.write(chunk)
    except (gzip.BadGzipFile, EOFError, zlib.error, zipfile.BadZipFile) as e:
        raise ValueError(f"The archive is damaged or incomplete: {e}") from None
