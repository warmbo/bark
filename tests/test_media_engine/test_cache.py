"""Cache keying, TTL, and LRU cleanup."""

import os
import time

from services.media_engine.cache import cache_key, cache_dir, cleanup, get, put


def test_key_deterministic_and_sensitive():
    payload = {"user": {"id": "1"}, "reputation": {"score": 1.5}}
    a = cache_key("profile", "g1", "u1", "bark", "procedural", payload)
    b = cache_key("profile", "g1", "u1", "bark", "procedural", payload)
    assert a == b
    assert a != cache_key("profile", "g1", "u2", "bark", "procedural", payload)
    assert a != cache_key("profile", "g1", "u1", "bark", "procedural",
                          {**payload, "reputation": {"score": 9.9}})


def test_put_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BARK_MEDIA_DATA_DIR", str(tmp_path))
    path = put("profile", "abc123", "png", b"PNGDATA")
    assert path.is_file()
    got = get("profile", "abc123", "png", ttl_s=60)
    assert got is not None and got.read_bytes() == b"PNGDATA"


def test_ttl_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv("BARK_MEDIA_DATA_DIR", str(tmp_path))
    path = put("profile", "abc123", "png", b"PNGDATA")
    old = time.time() - 3600
    os.utime(path, (old, old))
    assert get("profile", "abc123", "png", ttl_s=60) is None
    assert get("profile", "abc123", "png", ttl_s=7200) is not None


def test_cleanup_evicts_oldest(tmp_path, monkeypatch):
    monkeypatch.setenv("BARK_MEDIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARK_MEDIA_CACHE_MAX_BYTES", "150")  # room for ONE file
    p1 = put("profile", "aaa", "png", b"X" * 100)
    time.sleep(0.05)
    p2 = put("profile", "bbb", "png", b"Y" * 100)
    freed = cleanup()
    assert freed == 100
    assert not p1.is_file()  # oldest evicted
    assert p2.is_file()  # newest survives
