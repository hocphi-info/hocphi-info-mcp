"""Cache TTL trong bo nho + single-flight.

- TTL: moi muc het han sau `ttl` giay (dong ho tiem vao duoc, test khong phai cho).
- Single-flight: nhieu coroutine cung xin 1 khoa luc chua co (hoac het han) chi kich
  hoat MOT lan nap that; cac coroutine con lai cho ket qua do (chong "bay dan" khi
  cache het han).
- KHONG cache loi: ham nap nem exception thi khong luu gi, lan sau thu lai.
- Gioi han so muc (`max_entries`): vuot thi loai muc cu nhat (theo thu tu chen).

Cache nam trong bo nho cua tung instance — mat khi Cloud Run scale ve 0 (chap nhan).
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any


class TTLCache:
    def __init__(
        self,
        *,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[Hashable, asyncio.Future[Any]] = {}

    def __len__(self) -> int:
        return len(self._data)

    def _fresh(self, key: Hashable) -> tuple[bool, Any]:
        item = self._data.get(key)
        if item is None:
            return False, None
        expires_at, value = item
        if self._clock() >= expires_at:
            del self._data[key]
            return False, None
        return True, value

    async def get_or_load(
        self,
        key: Hashable,
        ttl: float,
        loader: Callable[[], Awaitable[Any]],
    ) -> tuple[Any, bool]:
        """Tra ve `(gia tri, cache_hit)`. `ttl <= 0`: khong luu (van single-flight)."""
        hit, value = self._fresh(key)
        if hit:
            return value, True

        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending), False

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await loader()
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # danh dau da xu ly, tranh canh bao "never retrieved"
            raise
        else:
            future.set_result(value)
            if ttl > 0:
                self._data[key] = (self._clock() + ttl, value)
                self._data.move_to_end(key)
                while len(self._data) > self._max_entries:
                    self._data.popitem(last=False)
            return value, False
        finally:
            self._inflight.pop(key, None)
