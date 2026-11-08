"""Atomic shared rate-limit counters for all Oracle Gunicorn worker processes.

Development retains the existing local-memory cache. Production uses a
dedicated file cache and an OS advisory lock, avoiding a Redis dependency or
schema change. All workers in the single authoritative Oracle Podman
container must share the same configured filesystem path.
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.cache import caches


def _increment(cache, key, window):
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        # The key can expire in between add and incr; start a new window.
        cache.set(key, 1, timeout=window)
        return 1


def increment_abuse_counter(key, window):
    if "abuse" not in settings.CACHES:
        return _increment(caches["default"], key, window)

    # The rate-limiter's own write lock must be shared by ALL Gunicorn workers.
    # FileBasedCache.incr() alone is not atomic between independent processes.
    import fcntl

    base = Path(settings.CACHES["abuse"]["LOCATION"])
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(base / ".counter.lock"), lock_flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return _increment(caches["abuse"], key, window)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
