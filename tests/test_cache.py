import asyncio

import pytest

from hocphi_mcp.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_second_call_within_ttl_is_a_hit_and_does_not_reload() -> None:
    cache = TTLCache(clock=FakeClock())
    calls = 0

    async def load() -> str:
        nonlocal calls
        calls += 1
        return "v"

    assert await cache.get_or_load("k", 10, load) == ("v", False)
    assert await cache.get_or_load("k", 10, load) == ("v", True)
    assert calls == 1


async def test_entry_expires_after_ttl() -> None:
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    n = 0

    async def load() -> int:
        nonlocal n
        n += 1
        return n

    assert (await cache.get_or_load("k", 10, load))[0] == 1
    clock.now = 9.9
    assert (await cache.get_or_load("k", 10, load)) == (1, True)
    clock.now = 10.0
    assert (await cache.get_or_load("k", 10, load)) == (2, False)


async def test_concurrent_callers_share_one_load() -> None:
    cache = TTLCache()
    calls = 0
    gate = asyncio.Event()

    async def load() -> str:
        nonlocal calls
        calls += 1
        await gate.wait()
        return "v"

    tasks = [asyncio.create_task(cache.get_or_load("k", 10, load)) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert calls == 1
    assert [r[0] for r in results] == ["v"] * 5


async def test_errors_are_not_cached_and_reach_every_waiter() -> None:
    cache = TTLCache()
    calls = 0

    async def boom() -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError):
        await cache.get_or_load("k", 10, boom)
    with pytest.raises(RuntimeError):
        await cache.get_or_load("k", 10, boom)
    assert calls == 2 and len(cache) == 0


async def test_max_entries_evicts_oldest() -> None:
    cache = TTLCache(max_entries=2)

    async def load() -> str:
        return "v"

    for key in ("a", "b", "c"):
        await cache.get_or_load(key, 10, load)
    assert len(cache) == 2
    assert (await cache.get_or_load("a", 10, load))[1] is False  # da bi loai
    assert (await cache.get_or_load("c", 10, load))[1] is True


async def test_zero_ttl_does_not_store() -> None:
    cache = TTLCache()

    async def load() -> str:
        return "v"

    await cache.get_or_load("k", 0, load)
    assert len(cache) == 0
