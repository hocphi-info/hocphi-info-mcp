"""Rate limit token bucket theo khoa (IP client), trong bo nho.

Moi khoa co mot "xo" `burst` token, nap lai `per_minute/60` token moi giay. Moi request
tieu 1 token; het token -> tu choi kem so giay phai cho (`Retry-After`).

Gioi han da biet (chap nhan, xem README): moi instance Cloud Run dem rieng, nen gioi han
thuc = `so instance x per_minute`; `--max-instances` lam tran cung. Bo nho bi chan bang
`max_clients` (LRU): khoa lau khong dung bi loai truoc.
"""

import math
import time
from collections import OrderedDict
from collections.abc import Callable


class TokenBucketLimiter:
    def __init__(
        self,
        *,
        per_minute: int,
        burst: int,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = per_minute / 60.0  # token / giay
        self._burst = float(burst)
        self._max_clients = max_clients
        self._clock = clock
        # key -> (so token con, thoi diem cap nhat). Thu tu = LRU (moi nhat o cuoi).
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._buckets)

    def check(self, key: str) -> tuple[bool, int]:
        """Tra ve `(duoc phep, retry_after_giay)`; `retry_after` = 0 khi duoc phep."""
        now = self._clock()
        tokens, updated = self._buckets.pop(key, (self._burst, now))
        tokens = min(self._burst, tokens + (now - updated) * self._rate)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            allowed, retry_after = True, 0
        else:
            self._buckets[key] = (tokens, now)
            allowed, retry_after = False, max(1, math.ceil((1.0 - tokens) / self._rate))
        while len(self._buckets) > self._max_clients:
            self._buckets.popitem(last=False)
        return allowed, retry_after
