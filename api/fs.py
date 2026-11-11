import json
import os
import tempfile


def write_atomic(path: str, data: bytes) -> None:
    # temp file in the same dir so os.replace is a rename, never a copy
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path: str, obj, **kwargs) -> None:
    write_atomic(path, json.dumps(obj, **kwargs).encode("utf-8"))
