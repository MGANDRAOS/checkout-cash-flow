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
            with _lock:
                _store[key] = (now, result)
            return result
        return wrapper
    return decorator


def clear_cache() -> None:
    """Flush the entire cache. Useful for testing or manual invalidation."""
    with _lock:
        _store.clear()
