"""
Where contributed raw logs live: a local directory by default, an S3
(or S3-compatible: R2, B2, MinIO) bucket when FLIGHTMD_S3_BUCKET is set.

Keys are made by us (content hash + suffix), never by the client, but they
are still checked so a bad one can't walk out of the directory.
"""

import os
import re
import shutil
import tempfile
from typing import Optional

from api import db
from api.config import get_settings

_KEY_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")


def _check_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in key:
        raise ValueError(f"bad blob key {key!r}")
    return key


class LocalBlobStore:
    def __init__(self, root: str):
        self.root = root

    def _path(self, key: str) -> str:
        return os.path.join(self.root, _check_key(key))

    def put(self, key: str, src_path: str) -> None:
        dest = self._path(key)
        os.makedirs(self.root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        os.close(fd)
        try:
            shutil.copyfile(src_path, tmp)
            os.replace(tmp, dest)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def delete(self, key: str) -> None:
        try:
            os.unlink(self._path(key))
        except FileNotFoundError:
            pass


class S3BlobStore:
    def __init__(self, bucket: str, prefix: str = "", endpoint_url: str = "", region: str = ""):
        try:
            import boto3
        except ImportError as e:
            raise RuntimeError(
                "FLIGHTMD_S3_BUCKET is set but boto3 isn't installed: pip install 'flightmd-core[s3]'"
            ) from e
        self.bucket = bucket
        self.prefix = prefix
        self._s3 = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region or None)

    def _key(self, key: str) -> str:
        return self.prefix + _check_key(key)

    def put(self, key: str, src_path: str) -> None:
        # a single PUT (or multipart) is all-or-nothing on S3, no temp object needed
        self._s3.upload_file(src_path, self.bucket, self._key(key))

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._key(key))


_s3: Optional[S3BlobStore] = None


def get():
    """S3 when a bucket is configured, else <data dir>/blobs."""
    global _s3
    s = get_settings()
    if s.flightmd_s3_bucket:
        if _s3 is None:
            _s3 = S3BlobStore(s.flightmd_s3_bucket, s.flightmd_s3_prefix, s.flightmd_s3_endpoint_url,
                              s.flightmd_s3_region)
        return _s3
    return LocalBlobStore(os.path.join(db.get().data_dir, "blobs"))
