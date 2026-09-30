"""HocphiApi: retry, 404, cache, xac thuc tham so. BE gia bang respx (khong mang)."""

import httpx
import pytest
import respx

from hocphi_mcp.api_client import USER_AGENT, HocphiApi
from hocphi_mcp.config import Settings
from hocphi_mcp.errors import BadResponse, InvalidArgument, NotFound, Unavailable
from tests.conftest import load_fixture

BASE = "https://api.test"
DETAIL = "/api/v1/schools/dh-bach-khoa-tphcm/majors/khoa-hoc-may-tinh"


class Sleeps:
    """Ghi lai cac lan `sleep` thay vi cho that."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest.fixture
def api(sleeps: Sleeps) -> HocphiApi:
    settings = Settings(_env_file=None, api_base_url=BASE)
    client = httpx.AsyncClient(
        base_url=BASE,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    return HocphiApi(settings, client=client, sleep=sleeps)


@respx.mock
async def test_ok_response_is_parsed_into_models(api: HocphiApi) -> None:
    respx.get(f"{BASE}{DETAIL}").respond(
        200, json=load_fixture("detail_hcmut_khmt.json")
    )
    d = await api.program_detail("dh-bach-khoa-tphcm", "khoa-hoc-may-tinh")
    assert len(d.programs) == 5


@respx.mock
async def test_sends_explicit_user_agent_and_accept(api: HocphiApi) -> None:
    route = respx.get(f"{BASE}/api/v1/taxonomy").respond(
        200, json=load_fixture("taxonomy_roots.json")
    )
    await api.taxonomy_roots()
    sent = route.calls.last.request.headers
    assert sent["user-agent"].startswith("hocphi-info-mcp/")
    assert sent["accept"] == "application/json"


@respx.mock
async def test_403_then_200_succeeds_after_backoff(
    api: HocphiApi, sleeps: Sleeps
) -> None:
    route = respx.get(f"{BASE}/api/v1/taxonomy").mock(
        side_effect=[
            httpx.Response(403),
            httpx.Response(200, json=load_fixture("taxonomy_roots.json")),
        ]
    )
    roots = await api.taxonomy_roots()
    assert len(roots.fields) == 20
    assert route.call_count == 2 and sleeps.calls == [0.3]


@respx.mock
async def test_repeated_503_becomes_unavailable_after_max_attempts(
    api: HocphiApi, sleeps: Sleeps
) -> None:
    route = respx.get(f"{BASE}/api/v1/taxonomy").respond(503)
    with pytest.raises(Unavailable) as info:
        await api.taxonomy_roots()
    assert info.value.attempts == 3 and info.value.retryable
    assert route.call_count == 3 and sleeps.calls == [0.3, 0.6]


@respx.mock
async def test_timeout_and_network_errors_are_retried_then_unavailable(
    api: HocphiApi,
) -> None:
    route = respx.get(f"{BASE}/api/v1/taxonomy").mock(
        side_effect=[
            httpx.ReadTimeout("slow"),
            httpx.ConnectError("down"),
            httpx.ReadTimeout("slow"),
        ]
    )
    with pytest.raises(Unavailable):
        await api.taxonomy_roots()
    assert route.call_count == 3


@respx.mock
async def test_404_is_not_found_and_is_not_retried(
    api: HocphiApi, sleeps: Sleeps
) -> None:
    route = respx.get(f"{BASE}{DETAIL}").respond(
        404, json={"detail": "Program not found"}
    )
    with pytest.raises(NotFound):
        await api.program_detail("dh-bach-khoa-tphcm", "khoa-hoc-may-tinh")
    assert route.call_count == 1 and sleeps.calls == []


@respx.mock
async def test_other_4xx_is_bad_response_without_retry(api: HocphiApi) -> None:
    route = respx.get(f"{BASE}/api/v1/majors").respond(422, json={"detail": "x"})
    with pytest.raises(BadResponse):
        await api.majors("cntt")
    assert route.call_count == 1


@respx.mock
async def test_schema_mismatch_is_bad_response(api: HocphiApi) -> None:
    respx.get(f"{BASE}/api/v1/taxonomy").respond(200, json={"fields": "not a list"})
    with pytest.raises(BadResponse):
        await api.taxonomy_roots()


@respx.mock
async def test_not_json_is_bad_response(api: HocphiApi) -> None:
    respx.get(f"{BASE}/api/v1/taxonomy").respond(200, text="<html>oops</html>")
    with pytest.raises(BadResponse):
        await api.taxonomy_roots()


@respx.mock
async def test_second_call_is_served_from_cache(api: HocphiApi) -> None:
    route = respx.get(f"{BASE}/api/v1/taxonomy").respond(
        200, json=load_fixture("taxonomy_roots.json")
    )
    await api.taxonomy_roots()
    await api.taxonomy_roots()
    assert route.call_count == 1


@respx.mock
async def test_errors_are_not_cached(api: HocphiApi) -> None:
    route = respx.get(f"{BASE}/api/v1/taxonomy").mock(side_effect=[httpx.Response(404)])
    with pytest.raises(NotFound):
        await api.taxonomy_roots()
    route.mock(
        side_effect=None,
        return_value=httpx.Response(200, json=load_fixture("taxonomy_roots.json")),
    )
    assert len((await api.taxonomy_roots()).fields) == 20


@respx.mock
async def test_search_query_is_sent_encoded_and_cached_per_query(
    api: HocphiApi,
) -> None:
    route = respx.get(f"{BASE}/api/v1/majors").respond(
        200, json=load_fixture("majors_search_cntt.json")
    )
    rows = await api.majors("  cntt ")
    await api.majors("cntt")
    assert route.call_count == 1 and rows
    assert route.calls.last.request.url.params["search"] == "cntt"


@pytest.mark.parametrize(
    "bad", ["../x", "a?b=c", "", "A-B", "x" * 81, "a b", "a/b", "tiếng-việt"]
)
async def test_bad_slugs_are_rejected_before_any_request(
    api: HocphiApi, bad: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200)
        with pytest.raises(InvalidArgument):
            await api.program_detail(bad, "khoa-hoc-may-tinh")
        with pytest.raises(InvalidArgument):
            await api.program_detail("dh-bach-khoa-tphcm", bad)
        assert route.call_count == 0


@pytest.mark.parametrize("bad", ["a", " ", "x" * 81])
async def test_bad_search_terms_are_rejected(api: HocphiApi, bad: str) -> None:
    with pytest.raises(InvalidArgument):
        await api.majors(bad)
    with pytest.raises(InvalidArgument):
        await api.schools(bad)


@pytest.mark.parametrize("bad", ["74", "7480", "748a", "../748", "UNCLASSIFIED", ""])
async def test_bad_taxonomy_codes_are_rejected(api: HocphiApi, bad: str) -> None:
    with pytest.raises(InvalidArgument):
        await api.taxonomy_node(bad)


@respx.mock
@pytest.mark.parametrize("code", ["748", "74801", "7480101", "unclassified"])
async def test_valid_taxonomy_codes_reach_the_backend(
    api: HocphiApi, code: str
) -> None:
    route = respx.get(f"{BASE}/api/v1/taxonomy/{code}").respond(
        200, json=load_fixture("taxonomy_748.json")
    )
    await api.taxonomy_node(code)
    assert route.call_count == 1
