"""App ASGI: bao ve (Host/Origin/Content-Type/body), rate limit, log, va giao thuc.

Phan lon goi thang app qua `httpx.ASGITransport`; mot bai e2e chay uvicorn that + SDK `Client`
(ca giao thuc cu `legacy` lan `auto`/moi). BE gia bang respx (khong dung `respx` cho
`Client` cua SDK vi no dung `httpx2`)."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx
import uvicorn
from mcp import Client

from hocphi_mcp.app import create_app
from hocphi_mcp.config import Settings
from hocphi_mcp.ratelimit import TokenBucketLimiter
from tests.conftest import load_fixture

API = "https://api.test"
HOST = "mcp.test"
ACCEPT = {"Accept": "application/json, text/event-stream"}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, api_base_url=API, allowed_hosts=[HOST], **kw)


@asynccontextmanager
async def running(
    settings: Settings | None = None, *, limiter: TokenBucketLimiter | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """App dang chay (lifespan bat) + client ASGI gia; moi thu trong CUNG task cua bai test."""
    app = create_app(settings or make_settings(), limiter=limiter)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{HOST}"
        ) as client:
            yield client


def log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


# ── /healthz ────────────────────────────────────────────────────────────────
async def test_healthz_is_ok_and_carries_a_request_id() -> None:
    async with running() as c:
        r = await c.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert len(r.headers["x-request-id"]) >= 8


async def test_healthz_is_exempt_from_rate_limit() -> None:
    limiter = TokenBucketLimiter(per_minute=1, burst=1, clock=Clock())
    async with running(limiter=limiter) as c:
        codes = [(await c.get("/healthz")).status_code for _ in range(10)]
    assert codes == [200] * 10


# ── Bao ve transport ────────────────────────────────────────────────────────
async def test_unknown_host_is_rejected_with_421() -> None:
    async with running() as c:
        r = await c.post("/mcp", json=LIST, headers={**ACCEPT, "Host": "evil.example"})
    assert r.status_code == 421


async def test_browser_origin_is_rejected_with_403() -> None:
    async with running() as c:
        r = await c.post(
            "/mcp", json=LIST, headers={**ACCEPT, "Origin": "https://evil.example"}
        )
    assert r.status_code == 403


async def test_non_json_content_type_is_400() -> None:
    async with running() as c:
        r = await c.post(
            "/mcp", content=b"x", headers={**ACCEPT, "Content-Type": "text/plain"}
        )
    assert r.status_code == 400


async def test_oversized_body_is_413() -> None:
    async with running(make_settings(max_body_bytes=2_048)) as c:
        r = await c.post(
            "/mcp",
            content=b"x" * 5_000,
            headers={**ACCEPT, "Content-Type": "application/json"},
        )
    assert r.status_code == 413


# ── Giao thuc: stateless ────────────────────────────────────────────────────
async def test_tools_list_works_without_initialize_and_issues_no_session() -> None:
    async with running() as c:
        r = await c.post("/mcp", json=LIST, headers=ACCEPT)
    assert r.status_code == 200 and "mcp-session-id" not in r.headers
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert len(names) == 7 and "search_majors" in names


@respx.mock(base_url=API, assert_all_called=False)
async def test_a_tool_call_returns_structured_content(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/api/v1/majors").respond(
        200, json=load_fixture("majors_search_cntt.json")
    )
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "search_majors", "arguments": {"query": "cntt"}},
    }
    async with running() as c:
        r = await c.post("/mcp", json=body, headers=ACCEPT)
    result = r.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["majors"][0]["slug"] == "cong-nghe-thong-tin"


# ── Rate limit ──────────────────────────────────────────────────────────────
async def test_rate_limit_returns_429_with_retry_after_then_recovers() -> None:
    clock = Clock()
    limiter = TokenBucketLimiter(per_minute=60, burst=2, clock=clock)
    hdr = {**ACCEPT, "X-Forwarded-For": "8.8.8.8, 1.1.1.1"}
    async with running(limiter=limiter) as c:
        assert [
            (await c.post("/mcp", json=LIST, headers=hdr)).status_code for _ in range(2)
        ] == [200, 200]
        blocked = await c.post("/mcp", json=LIST, headers=hdr)
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "1"
        assert blocked.json()["error"] == "rate_limited"
        # Nguon khac khong bi anh huong.
        other = await c.post(
            "/mcp", json=LIST, headers={**ACCEPT, "X-Forwarded-For": "8.8.8.8, 2.2.2.2"}
        )
        assert other.status_code == 200
        clock.now += 2
        assert (await c.post("/mcp", json=LIST, headers=hdr)).status_code == 200


async def test_spoofing_the_left_side_of_forwarded_for_does_not_dodge_the_limit() -> (
    None
):
    limiter = TokenBucketLimiter(per_minute=60, burst=1, clock=Clock())
    async with running(limiter=limiter) as c:
        first = await c.post(
            "/mcp", json=LIST, headers={**ACCEPT, "X-Forwarded-For": "a, 1.1.1.1"}
        )
        second = await c.post(
            "/mcp", json=LIST, headers={**ACCEPT, "X-Forwarded-For": "b, 1.1.1.1"}
        )
    assert (first.status_code, second.status_code) == (200, 429)


# ── Nhat ky ─────────────────────────────────────────────────────────────────
async def test_access_log_is_one_json_line_without_the_raw_ip(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with running() as c:
        await c.get("/healthz", headers={"X-Forwarded-For": "203.0.113.77"})
        await c.get("/nope")
    out_lines = log_lines(capsys)
    reqs = [line for line in out_lines if line["message"] == "request"]
    assert [(r["path"], r["status"]) for r in reqs] == [
        ("/healthz", 200),
        ("/nope", 404),
    ]
    first = reqs[0]
    assert first["severity"] == "INFO" and isinstance(first["duration_ms"], int)
    assert len(first["client"]) == 12 and first["method"] == "GET"
    assert "203.0.113.77" not in json.dumps(out_lines)


async def test_request_id_reaches_tool_logs_and_is_echoed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.get("/api/v1/majors").respond(
            200, json=load_fixture("majors_search_cntt.json")
        )
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_majors", "arguments": {"query": "cntt"}},
        }
        async with running() as c:
            r = await c.post(
                "/mcp", json=body, headers={**ACCEPT, "X-Request-Id": "abc-12345678"}
            )
    assert r.headers["x-request-id"] == "abc-12345678"
    lines = log_lines(capsys)
    call = next(line for line in lines if line["message"] == "tool_call")
    assert call["tool"] == "search_majors" and call["request_id"] == "abc-12345678"
    assert call["error_code"] is None and call["n_results"] == 1


async def test_bad_supplied_request_id_is_replaced() -> None:
    async with running() as c:
        r = await c.get("/healthz", headers={"X-Request-Id": "bad id with spaces!"})
    assert r.headers["x-request-id"] != "bad id with spaces!"


async def test_cloud_trace_header_becomes_the_logging_trace_field(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with running(make_settings(gcp_project="my-proj")) as c:
        await c.get(
            "/healthz",
            headers={"X-Cloud-Trace-Context": "105445aa7843bc8bf206b12000100000/1;o=1"},
        )
    req = next(line for line in log_lines(capsys) if line["message"] == "request")
    assert req["logging.googleapis.com/trace"] == (
        "projects/my-proj/traces/105445aa7843bc8bf206b12000100000"
    )


async def test_library_logs_are_json_too(capsys: pytest.CaptureFixture[str]) -> None:
    async with running() as c:
        await c.post("/mcp", json=LIST, headers={**ACCEPT, "Host": "evil.example"})
    warn = [line for line in log_lines(capsys) if line["severity"] == "WARNING"]
    assert any("Invalid Host header" in line["message"] for line in warn)


# ── E2E: uvicorn that + SDK Client (giao thuc cu va moi) ───────────────────
@asynccontextmanager
async def serving(app: Any) -> AsyncIterator[str]:
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_config=None, lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:  # noqa: ASYNC110 - uvicorn khong co Event de cho
            await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await task


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_end_to_end_with_the_sdk_client(mode: str) -> None:
    settings = Settings(_env_file=None, api_base_url=API)  # host mac dinh: 127.0.0.1:*
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.get("/api/v1/taxonomy").respond(
            200, json=load_fixture("taxonomy_roots.json")
        )
        async with (
            serving(create_app(settings)) as url,
            Client(url, mode=mode) as client,
        ):
            tools = (await client.list_tools()).tools
            result = await client.call_tool("explore_major_taxonomy", {})
    assert len(tools) == 7
    assert not result.is_error and len(result.structured_content["children"]) == 20
