# cache_utils.py
"""
Thread-safe in-process TTL cache for analytics endpoints.

Prevents redundant MSSQL round-trips when the same analytics panel is loaded
by multiple users or rapid page refreshes within the TTL window.

Note: cache is per-process. Not shared across gunicorn workers (use Redis
for multi-process deployments). Fine for single-worker Flask dev server.
"""
import time
import functools
import threading
from typing import Any, Callable

_lock: threading.Lock = threading.Lock()
_store: dict = {}  # key → (timestamp, cached_value)


def ttl_cache(seconds: int = 60):
    """
    Decorator: cache function return value for <seconds>.
    Cache key = function identity + all positional/keyword arguments.

    Thread-safety: the _store dict is protected by a lock. Under concurrent
    access, two threads that both miss the cache may both call fn() before
    either writes. The double-check on write prevents stale overwrites, but
    duplicate executions during the same miss window are possible (best-effort
    at-most-once-per-TTL, not strict). This is acceptable for the single-worker
    Flask dev server deployment.

    Usage:
        @ttl_cache(seconds=60)
        def get_kpis() -> dict: ...

        @ttl_cache(seconds=300)
        def get_affinity_pairs(days: int = 30, top: int = 15) -> list: ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{fn.__module__}.{fn.__qualname__}|{args!r}|{sorted(kwargs.items())!r}"
            now = time.monotonic()
            with _lock:
                if key in _store:
                    ts, val = _store[key]
                    if now - ts < seconds:
                        return val
            result = fn(*args, **kwargs)
            stored_at = time.monotonic()
            with _lock:
                # Double-check: another thread may have already populated the key
                if key in _store and (stored_at - _store[key][0] < seconds):
                    return _store[key][1]
                _store[key] = (stored_at, result)
            return result
        return wrapper
    return decorator


def clear_cache() -> None:
    """Flush the entire cache. Useful for testing or manual invalidation."""
    with _lock:
        _store.clear()
