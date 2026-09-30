"""Client goi API hocphi (REST cong khai) — nguon so lieu DUY NHAT cua MCP.

MCP khong chua quy tac hoc phi nao: moi so (nam 1, tong khoa, du phong, khoang
min-max) do BE tinh, o day chi lay ve, kiem tra schema, cache va bao loi co kieu.

- Retry (giong `apiFetch` cua hocphi-info-fe): thu lai 403/408/429/5xx va loi mang.
  403 nam trong tap vi Fly proxy tra 403 thoang qua khi may dang resume tu suspend.
  404 -> `NotFound` ngay; 4xx khac -> `BadResponse` (loi cua ta, khong thu lai).
- Cache TTL + single-flight (xem cache.py); khong cache loi.
- Tham so nguoi dung chi di vao path (da kiem regex) hoac query do httpx ma hoa; chi goi
  `api_base_url` co dinh -> khong the bi lai thanh SSRF.
- Dong ho va `sleep` tiem vao duoc de test retry khong phai cho that.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
import structlog
from pydantic import TypeAdapter, ValidationError

from hocphi_mcp import __version__
from hocphi_mcp.api_models import (
    MajorRowOut,
    ProgramDetailResponseOut,
    SchoolRowOut,
    TaxonomyNodeDetailOut,
    TaxonomyRootsOut,
)
from hocphi_mcp.cache import TTLCache
from hocphi_mcp.config import Settings
from hocphi_mcp.errors import BadResponse, InvalidArgument, NotFound, Unavailable

logger = structlog.get_logger("hocphi_mcp.api")

T = TypeVar("T")

USER_AGENT = f"hocphi-info-mcp/{__version__} (+https://hocphi.info)"
RETRYABLE_STATUS = frozenset({403, 408, 429, 500, 502, 503, 504})
BACKOFF_BASE_S = 0.3  # 0,3 s roi 0,6 s — giong FE

SLUG_RE = re.compile(r"^[a-z0-9-]{1,80}$")
TAXONOMY_CODE_RE = re.compile(r"^(\d{3}|\d{5}|\d{7}|unclassified)$")
MIN_SEARCH_LEN = 2
MAX_SEARCH_LEN = 80


def _check_slug(value: str, what: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise InvalidArgument(
            f"{what} khong hop le: chi gom a-z, 0-9, '-' (toi da 80)."
        )
    return value


def _check_search(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not MIN_SEARCH_LEN <= len(value) <= MAX_SEARCH_LEN:
        raise InvalidArgument(
            f"Tu khoa tim kiem phai dai {MIN_SEARCH_LEN}-{MAX_SEARCH_LEN} ky tu."
        )
    return value


_MAJOR_ROWS = TypeAdapter(list[MajorRowOut])
_SCHOOL_ROWS = TypeAdapter(list[SchoolRowOut])


class HocphiApi:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._s = settings
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=settings.http_timeout_s,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._cache = TTLCache(max_entries=settings.cache_max_entries, clock=clock)
        self._clock = clock
        self._sleep = sleep

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    # ── Endpoint ────────────────────────────────────────────────────────────
    async def majors(self, search: str | None = None) -> list[MajorRowOut]:
        search = _check_search(search)
        params = {"search": search} if search else None
        return await self._get(
            "/api/v1/majors", params, _MAJOR_ROWS, self._s.cache_ttl_lists_s
        )

    async def schools(self, search: str | None = None) -> list[SchoolRowOut]:
        search = _check_search(search)
        params = {"search": search} if search else None
        return await self._get(
            "/api/v1/schools", params, _SCHOOL_ROWS, self._s.cache_ttl_lists_s
        )

    async def program_detail(
        self, school_slug: str, major_slug: str
    ) -> ProgramDetailResponseOut:
        _check_slug(school_slug, "school_slug")
        _check_slug(major_slug, "major_slug")
        return await self._get(
            f"/api/v1/schools/{school_slug}/majors/{major_slug}",
            None,
            TypeAdapter(ProgramDetailResponseOut),
            self._s.cache_ttl_detail_s,
        )

    async def taxonomy_roots(self) -> TaxonomyRootsOut:
        return await self._get(
            "/api/v1/taxonomy",
            None,
            TypeAdapter(TaxonomyRootsOut),
            self._s.cache_ttl_lists_s,
        )

    async def taxonomy_node(self, code: str) -> TaxonomyNodeDetailOut:
        if not TAXONOMY_CODE_RE.fullmatch(code):
            raise InvalidArgument(
                "Ma phai la 3, 5 hoac 7 chu so (linh vuc, nhom nganh, nganh) "
                "hoac 'unclassified'."
            )
        return await self._get(
            f"/api/v1/taxonomy/{code}",
            None,
            TypeAdapter(TaxonomyNodeDetailOut),
            self._s.cache_ttl_lists_s,
        )

    # ── Loi goi HTTP ────────────────────────────────────────────────────────
    async def _get(
        self,
        path: str,
        params: dict[str, str] | None,
        adapter: TypeAdapter[T],
        ttl: float,
    ) -> T:
        key = (path, tuple(sorted((params or {}).items())))

        async def load() -> T:
            payload = await self._fetch_json(path, params)
            try:
                return adapter.validate_python(payload)
            except ValidationError as exc:
                logger.error(
                    "upstream_schema_mismatch", path=path, errors=exc.error_count()
                )
                raise BadResponse(
                    f"Phan hoi tu {path} khong khop schema (BE da doi hop dong?)."
                ) from exc

        value, cache_hit = await self._cache.get_or_load(key, ttl, load)
        if cache_hit:
            logger.info("upstream_call", path=path, cache_hit=True)
        return value

    async def _fetch_json(self, path: str, params: dict[str, str] | None) -> Any:
        started = self._clock()
        attempts = 0
        last: str = "khong ro"
        while attempts < self._s.http_max_attempts:
            attempts += 1
            try:
                resp = await self._http.get(path, params=params)
            except httpx.HTTPError as exc:  # timeout, ket noi, doc that bai...
                last = type(exc).__name__
            else:
                if resp.status_code == 404:
                    logger.info(
                        "upstream_call", path=path, status=404, attempts=attempts
                    )
                    raise NotFound(f"Khong tim thay: {path}")
                if resp.is_success:
                    logger.info(
                        "upstream_call",
                        path=path,
                        status=resp.status_code,
                        attempts=attempts,
                        cache_hit=False,
                        duration_ms=round((self._clock() - started) * 1000),
                    )
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise BadResponse(f"{path} khong tra ve JSON hop le.") from exc
                if resp.status_code not in RETRYABLE_STATUS:
                    logger.error(
                        "upstream_bad_status", path=path, status=resp.status_code
                    )
                    raise BadResponse(f"{path} tra ve HTTP {resp.status_code}.")
                last = f"HTTP {resp.status_code}"
            if attempts < self._s.http_max_attempts:
                await self._sleep(BACKOFF_BASE_S * 2 ** (attempts - 1))

        logger.warning("upstream_unavailable", path=path, attempts=attempts, last=last)
        raise Unavailable(
            f"API hocphi tam thoi khong tra loi ({last}). Thu lai sau it phut.",
            attempts=attempts,
        )
