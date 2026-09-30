"""Hai middleware ASGI thuan (khong dung BaseHTTPMiddleware, de ngu canh log truyen dung).

Thu tu (ngoai -> trong): RequestContext (id + trace + access log) -> RateLimit -> app.
"""

import re
import time
import uuid
from collections.abc import Iterable

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hocphi_mcp.logging import hash_client, parse_cloud_trace
from hocphi_mcp.ratelimit import TokenBucketLimiter

logger = structlog.get_logger("hocphi_mcp.http")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
TRACE_FIELD = "logging.googleapis.com/trace"


def client_ip(scope: Scope, hops: int) -> str:
    """IP client that.

    Sau `hops` proxy tin cay (Cloud Run: Google Front End, 1 hop), moi proxy NOI THEM IP
    nguon vao CUOI `X-Forwarded-For`; phan ben trai la do client tu khai nen co the gia mao.
    Vi vay lay phan tu thu `hops` tinh tu PHAI. Khong co header (chay local) thi dung IP ket noi.
    """
    if hops > 0:
        raw = Headers(scope=scope).get("x-forwarded-for", "")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, gcp_project: str | None, hops: int) -> None:
        self.app = app
        self.gcp_project = gcp_project
        self.hops = hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        supplied = headers.get("x-request-id", "")
        request_id = (
            supplied if _REQUEST_ID_RE.fullmatch(supplied) else uuid.uuid4().hex
        )
        ctx: dict[str, str] = {"request_id": request_id}
        trace = parse_cloud_trace(
            headers.get("x-cloud-trace-context"), self.gcp_project
        )
        if trace:
            ctx[TRACE_FIELD] = trace
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(**ctx)

        status = 500  # neu app nem loi truoc khi gui response
        started = time.monotonic()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.monotonic() - started) * 1000),
                client=hash_client(client_ip(scope, self.hops)),
                user_agent=headers.get("user-agent", "")[:80],
                bytes_in=int(headers.get("content-length", "0") or 0)
                if headers.get("content-length", "0").isdigit()
                else None,
            )


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: TokenBucketLimiter,
        hops: int,
        exempt_paths: Iterable[str] = ("/healthz",),
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.hops = hops
        self.exempt = frozenset(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt:
            await self.app(scope, receive, send)
            return

        allowed, retry_after = self.limiter.check(client_ip(scope, self.hops))
        if allowed:
            await self.app(scope, receive, send)
            return

        logger.warning("rate_limited", retry_after_s=retry_after)
        response = JSONResponse(
            {
                "error": "rate_limited",
                "message": f"Too many requests. Retry in {retry_after} seconds.",
                "retry_after_seconds": retry_after,
            },
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)
