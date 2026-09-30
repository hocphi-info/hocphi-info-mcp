import pytest

from hocphi_mcp.ratelimit import TokenBucketLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(
    per_minute: int = 60, burst: int = 3, max_clients: int = 100
) -> tuple[TokenBucketLimiter, Clock]:
    clock = Clock()
    return (
        TokenBucketLimiter(
            per_minute=per_minute, burst=burst, max_clients=max_clients, clock=clock
        ),
        clock,
    )


def test_burst_is_allowed_then_blocked_with_retry_after() -> None:
    limiter, _ = make(per_minute=60, burst=3)
    assert [limiter.check("a")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.check("a")
    assert allowed is False and retry_after == 1  # 1 token/giay


def test_tokens_refill_over_time_but_never_beyond_burst() -> None:
    limiter, clock = make(per_minute=60, burst=3)
    for _ in range(3):
        limiter.check("a")
    assert limiter.check("a")[0] is False
    clock.now += 1.0
    assert limiter.check("a")[0] is True  # 1 token nap lai
    assert limiter.check("a")[0] is False
    clock.now += 3600
    assert [limiter.check("a")[0] for _ in range(4)] == [True, True, True, False]


def test_clients_are_independent() -> None:
    limiter, _ = make(burst=1)
    assert limiter.check("a")[0] is True
    assert limiter.check("a")[0] is False
    assert limiter.check("b")[0] is True


def test_retry_after_reflects_a_slow_rate() -> None:
    limiter, _ = make(per_minute=1, burst=1)
    limiter.check("a")
    allowed, retry_after = limiter.check("a")
    assert allowed is False and retry_after == 60


def test_memory_is_bounded_and_evicted_keys_start_fresh() -> None:
    limiter, _ = make(burst=1, max_clients=3)
    for key in ("a", "b", "c", "d", "e"):
        limiter.check(key)
    assert len(limiter) == 3
    # "a" da bi loai (LRU) nen duoc cap xo day lai; "e" van dang het token.
    assert limiter.check("a")[0] is True
    assert limiter.check("e")[0] is False


@pytest.mark.parametrize("bad", [0, -1])
def test_zero_rate_is_rejected_by_settings_not_limiter(bad: int) -> None:
    from pydantic import ValidationError

    from hocphi_mcp.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, rate_limit_per_minute=bad)
