"""Cau hinh tu bien moi truong (12-factor) — `pydantic-settings`.

Moi gia tri co mac dinh dung cho production; dev ghi de bang env hoac `.env`.
"""

from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Goi thang origin Fly, KHONG qua api.hocphi.info: sau Cloudflare, mot so User-Agent
    # bi chan (403) va chua biet Cloudflare co chan IP Cloud Run khong. Server-to-server
    # khong can lop do; xem docs/plans (chang B / U3).
    api_base_url: str = "https://hocphi-info-api.fly.dev"
    web_base_url: str = "https://hocphi.info"

    http_timeout_s: float = Field(12.0, gt=0, le=60)
    http_max_attempts: int = Field(3, ge=1, le=5)

    cache_ttl_lists_s: float = Field(600.0, ge=0)
    cache_ttl_detail_s: float = Field(120.0, ge=0)
    cache_max_entries: int = Field(256, ge=1)

    log_level: str = "INFO"

    @field_validator("api_base_url", "web_base_url")
    @classmethod
    def _https_unless_local(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"URL khong hop le: {v!r}")
        if parsed.scheme == "http" and parsed.hostname not in _LOCAL_HOSTS:
            raise ValueError("Chi cho phep http:// voi localhost; dung https://")
        return v.rstrip("/")
