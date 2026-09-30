import pytest
from pydantic import ValidationError

from hocphi_mcp.config import Settings


def test_defaults_point_at_fly_origin_over_https() -> None:
    s = Settings(_env_file=None)
    assert s.api_base_url == "https://hocphi-info-api.fly.dev"
    assert s.http_max_attempts == 3 and s.http_timeout_s == 12


def test_http_is_rejected_outside_localhost() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_base_url="http://example.com")


def test_http_is_allowed_for_localhost_and_trailing_slash_is_stripped() -> None:
    s = Settings(_env_file=None, api_base_url="http://localhost:8000/")
    assert s.api_base_url == "http://localhost:8000"


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BASE_URL", "https://api.hocphi.info")
    assert Settings(_env_file=None).api_base_url == "https://api.hocphi.info"


@pytest.mark.parametrize("bad", ["ftp://x.y", "not a url", "https://"])
def test_garbage_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_base_url=bad)
