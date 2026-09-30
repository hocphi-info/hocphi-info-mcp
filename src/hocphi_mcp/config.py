"""Cau hinh tu bien moi truong (12-factor) — `pydantic-settings`.

Moi gia tri co mac dinh dung cho production; dev ghi de bang env hoac `.env`.
"""

from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    # ── May chu HTTP (U5) ───────────────────────────────────────────────────
    port: int = 8080  # Cloud Run dat $PORT
    # Host duoc phep (chong DNS rebinding). Mac dinh chi localhost; production dat
    # ALLOWED_HOSTS="<ten-dich-vu>.<vung>.run.app" (them ":*" de nhan moi cong).
    # Phan tach bang dau phay (NoDecode: khong ep phai la JSON).
    allowed_hosts: Annotated[list[str], NoDecode] = [
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
    ]
    max_body_bytes: int = Field(65_536, ge=1_024)

    # Rate limit theo IP client, TRONG BO NHO cua tung instance: gioi han that =
    # so instance x nguong nay (max-instances la tran cung). Xem README.
    rate_limit_per_minute: int = Field(60, ge=1)
    rate_limit_burst: int = Field(20, ge=1)
    rate_limit_max_clients: int = Field(10_000, ge=100)
    # So proxy tin cay dung truoc app (Cloud Run: 1 — Google Front End). IP client la
    # phan tu thu N tinh tu PHAI cua X-Forwarded-For (phan ben trai la do client tu khai).
    trusted_proxy_hops: int = Field(1, ge=0, le=5)

    # Co project id thi log co `logging.googleapis.com/trace` de gan log vao trace.
    gcp_project: str | None = None

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, v: object) -> object:
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        return v

    @field_validator("api_base_url", "web_base_url")
    @classmethod
    def _https_unless_local(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"URL khong hop le: {v!r}")
        if parsed.scheme == "http" and parsed.hostname not in _LOCAL_HOSTS:
            raise ValueError("Chi cho phep http:// voi localhost; dung https://")
        return v.rstrip("/")
