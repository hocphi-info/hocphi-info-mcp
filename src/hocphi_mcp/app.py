"""Ung dung ASGI: Starlette + middleware + /healthz + MCP tai /mcp.

    uvicorn hocphi_mcp.app:create_app --factory --port 8080      # hoac: python -m hocphi_mcp

Lop bao ve (ngoai -> trong): RequestContext (request-id, trace, access log) -> RateLimit
(theo IP) -> [Host/Origin/Content-Type + gioi han body cua SDK] -> tool. `stateless_http`:
moi request la mot phien tam (khong `Mcp-Session-Id`, khong can sticky session tren Cloud
Run); giao thuc moi (2026-07-28) von khong co phien.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from hocphi_mcp import __version__
from hocphi_mcp.api_client import HocphiApi
from hocphi_mcp.config import Settings
from hocphi_mcp.logging import configure_logging
from hocphi_mcp.middleware import RateLimitMiddleware, RequestContextMiddleware
from hocphi_mcp.ratelimit import TokenBucketLimiter
from hocphi_mcp.server import build_server


async def healthz(_: Request) -> JSONResponse:
    # Chi noi "tien trinh song" — KHONG goi BE (probe cua Cloud Run phai re va khong phu
    # thuoc dich vu ngoai).
    return JSONResponse({"status": "ok", "version": __version__})


def create_app(
    settings: Settings | None = None,
    *,
    api: HocphiApi | None = None,
    limiter: TokenBucketLimiter | None = None,
) -> Starlette:
    # Dung `is None`, KHONG `or`: TokenBucketLimiter co __len__ nen limiter rong la "falsy"
    # va `limiter or ...` se am tham thay bang bo mac dinh.
    if settings is None:
        settings = Settings()
    configure_logging(settings.log_level)
    if api is None:
        api = HocphiApi(settings)
    if limiter is None:
        limiter = TokenBucketLimiter(
            per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
            max_clients=settings.rate_limit_max_clients,
        )

    mcp = build_server(api, settings)
    mcp_app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=settings.max_body_bytes,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            # Khong cho origin trinh duyet nao: client chinh thuc goi tu server, khong CORS.
            allowed_origins=[],
        ),
    )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        # Khi mount, lifespan rieng cua app MCP bi tat -> ta phai chay session manager.
        async with mcp.session_manager.run():
            yield
        await api.aclose()

    return Starlette(
        routes=[Route("/healthz", healthz), Mount("/", app=mcp_app)],
        middleware=[
            Middleware(
                RequestContextMiddleware,
                gcp_project=settings.gcp_project,
                hops=settings.trusted_proxy_hops,
            ),
            Middleware(
                RateLimitMiddleware, limiter=limiter, hops=settings.trusted_proxy_hops
            ),
        ],
        lifespan=lifespan,
    )
