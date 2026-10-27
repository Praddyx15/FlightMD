import gzip
import os
import time

import pandas as pd
import pytest

from flightmd_core import cache
from flightmd_core.models.metadata import FlightMetadata

SHA = "a" * 64
OTHER = "b" * 64


@pytest.fixture
def cache_on(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHTMD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FLIGHTMD_CACHE", "1")
    monkeypatch.delenv("FLIGHTMD_CACHE_TTL_S", raising=False)
    monkeypatch.delenv("FLIGHTMD_CACHE_MAX_MB", raising=False)
    return tmp_path / "cache"


def parsed():
    topics = {"sensor_accel": pd.DataFrame({"timestamp": [0, 1000], "x": [0.1, 0.2]})}
    params = {"MC_ROLLRATE_P": 0.15}
    metadata = FlightMetadata(duration_seconds=12.5, source_format="px4_ulog", log_sha256=SHA)
    return topics, params, metadata


def test_round_trip(cache_on):
    cache.put(SHA, *parsed())
    topics, params, metadata = cache.get(SHA)

    pd.testing.assert_frame_equal(topics["sensor_accel"], parsed()[0]["sensor_accel"])
    assert params == {"MC_ROLLRATE_P": 0.15}
    assert metadata.duration_seconds == 12.5
    assert metadata.source_format == "px4_ulog"


def test_miss(cache_on):
    assert cache.get(OTHER) is None


def test_no_temp_files_left(cache_on):
    cache.put(SHA, *parsed())
    assert [p.name for p in cache_on.iterdir() if p.name.startswith(".tmp-")] == []


def test_expired_entry_is_dropped(cache_on, monkeypatch):
    cache.put(SHA, *parsed())
    path = next(cache_on.iterdir())
    old = time.time() - 7200
    os.utime(path, (old, old))

    assert cache.get(SHA) is None
    assert not path.exists()


def test_ttl_from_env(cache_on, monkeypatch):
    monkeypatch.setenv("FLIGHTMD_CACHE_TTL_S", "100000")
    cache.put(SHA, *parsed())
    path = next(cache_on.iterdir())
    old = time.time() - 7200
    os.utime(path, (old, old))
    assert cache.get(SHA) is not None


def test_size_cap_drops_oldest_first(cache_on, monkeypatch):
    cache.put(SHA, *parsed())
    first = next(cache_on.iterdir())
    old = time.time() - 600
    os.utime(first, (old, old))

    # smaller than two entries, bigger than one
    monkeypatch.setenv("FLIGHTMD_CACHE_MAX_MB", str(first.stat().st_size * 1.5 / 1e6))
    cache.put(OTHER, *parsed())

    assert cache.get(SHA) is None
    assert cache.get(OTHER) is not None


def test_corrupt_entry_is_a_miss_and_removed(cache_on):
    cache.put(SHA, *parsed())
    path = next(cache_on.iterdir())
    path.write_bytes(gzip.compress(b"not a pickle"))

    assert cache.get(SHA) is None
    assert not path.exists()


def test_old_cache_version_is_pruned(cache_on):
    cache_on.mkdir(parents=True)
    stale = cache_on / f"{SHA}.v0.pkl.gz"
    stale.write_bytes(b"x")
    cache.prune()
    assert not stale.exists()


@pytest.mark.parametrize("key", ["../../etc/passwd", "A" * 64, "abc", ""])
def test_rejects_anything_but_a_sha256(cache_on, key):
    with pytest.raises(ValueError):
        cache.get(key)


def test_off_by_default_without_data_dir(monkeypatch):
    monkeypatch.delenv("FLIGHTMD_CACHE", raising=False)
    monkeypatch.delenv("FLIGHTMD_DATA_DIR", raising=False)
    assert not cache.enabled()
    assert cache.get(SHA) is None


def test_on_by_default_with_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("FLIGHTMD_CACHE", raising=False)
    monkeypatch.setenv("FLIGHTMD_DATA_DIR", str(tmp_path))
    assert cache.enabled()


def test_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHTMD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FLIGHTMD_CACHE", "0")
    cache.put(SHA, *parsed())
    assert not (tmp_path / "cache").exists()
