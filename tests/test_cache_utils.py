# tests/test_cache_utils.py
import time
from cache_utils import ttl_cache, clear_cache


def test_cache_returns_same_value_on_second_call():
    call_count = {"n": 0}

    @ttl_cache(seconds=60)
    def fn(x):
        call_count["n"] += 1
        return x * 2

    assert fn(5) == 10
    assert fn(5) == 10
    assert call_count["n"] == 1  # only called once — second hit from cache


def test_different_args_produce_different_cache_keys():
    call_count = {"n": 0}

    @ttl_cache(seconds=60)
    def fn(x):
        call_count["n"] += 1
        return x

    fn(1)
    fn(2)
    assert call_count["n"] == 2  # different args → distinct cache entries


def test_expired_entry_calls_function_again():
    call_count = {"n": 0}

    @ttl_cache(seconds=1)
    def fn(x):
        call_count["n"] += 1
        return x

    fn(99)
    time.sleep(1.1)
    fn(99)
    assert call_count["n"] == 2  # TTL expired → re-executed


def test_clear_cache_forces_re_execution():
    call_count = {"n": 0}

    @ttl_cache(seconds=60)
    def fn(x):
        call_count["n"] += 1
        return x

    fn(7)
    clear_cache()
    fn(7)
    assert call_count["n"] == 2  # cache was cleared → re-executed
