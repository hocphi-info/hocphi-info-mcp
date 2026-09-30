"""7 tool MCP, goi qua client MCP trong bo nho (`mcp.Client`) den mot HocphiApi that,
con BE gia bang respx voi response THAT luu o tests/fixtures."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer
from structlog.testing import capture_logs

from hocphi_mcp.api_client import USER_AGENT, HocphiApi
from hocphi_mcp.config import Settings
from hocphi_mcp.server import build_server
from tests.conftest import load_fixture

BASE = "https://api.test"
HCMUT = "/api/v1/schools/dh-bach-khoa-tphcm/majors/khoa-hoc-may-tinh"
HUTECH = "/api/v1/schools/hutech/majors/khoa-hoc-may-tinh"
IU = "/api/v1/schools/dh-quoc-te-tphcm/majors/khoa-hoc-may-tinh"
UIT = "/api/v1/schools/uit/majors/khoa-hoc-may-tinh"

TOOLS = {
    "search_majors",
    "search_schools",
    "get_major_tuition",
    "compare_programs",
    "estimate_total_cost",
    "explore_major_taxonomy",
    "find_related_majors",
}


@dataclass
class Env:
    """Moi lan goi mo mot `Client` moi trong bo nho (tool stateless nen khong khac gi).

    Khong giu `Client` trong fixture async: no mo task group cua anyio va pytest-asyncio
    dong fixture o task khac ("cancel scope in a different task")."""

    router: respx.MockRouter
    server: MCPServer

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        async with Client(self.server) as client:
            return await client.call_tool(name, args)

    async def list_tools(self) -> Any:
        async with Client(self.server) as client:
            return await client.list_tools()

    def get(self, path: str, fixture: str | None = None, **kw: Any) -> respx.Route:
        route = self.router.get(path, **kw)
        if fixture:
            route.respond(200, json=load_fixture(fixture))
        return route


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    async def no_sleep(_: float) -> None:
        return None

    settings = Settings(_env_file=None, api_base_url=BASE)
    http = httpx.AsyncClient(
        base_url=BASE, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        api = HocphiApi(settings, client=http, sleep=no_sleep)
        yield Env(router, build_server(api, settings))
    await http.aclose()


def _err_text(result: Any) -> str:
    return str(result.content[0].text)


def _all_details(e: Env) -> None:
    e.get(HCMUT, "detail_hcmut_khmt.json")
    e.get(HUTECH, "detail_hutech_khmt.json")
    e.get(IU, "detail_dhqt_khmt.json")
    e.router.get(UIT).respond(404, json={"detail": "Program not found"})


# ── Danh sach tool ──────────────────────────────────────────────────────────
async def test_seven_read_only_tools_with_output_schemas(env: Env) -> None:
    tools = (await env.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations is not None
        assert t.annotations.read_only_hint is True
        assert t.annotations.destructive_hint is False
        assert t.output_schema, t.name
        assert t.description, t.name


# ── search_majors / search_schools ──────────────────────────────────────────
async def test_search_majors_groups_rows_and_uses_alias_results(env: Env) -> None:
    env.get("/api/v1/majors", "majors_search_cntt.json", params={"search": "cntt"})
    r = await env.call("search_majors", {"query": "cntt"})
    assert not r.is_error
    d = r.structured_content
    fixture_slugs = {
        x["major"]["slug"] for x in load_fixture("majors_search_cntt.json")
    }
    assert {h["slug"] for h in d["majors"]} == fixture_slugs
    hit = d["majors"][0]
    assert hit["slug"] == "cong-nghe-thong-tin" and "cntt" in hit["aliases"]
    assert hit["official_code"] == "7480201" and hit["field"]["code"] == "748"
    assert hit["n_schools"] == len(hit["schools"]) <= 8
    assert hit["web_url"] == "https://hocphi.info/nganh?major=cong-nghe-thong-tin"
    rng = hit["year1_range_dai_tra"]
    assert rng["min"]["vnd"] <= rng["max"]["vnd"]
    assert rng["min"]["million"] == pytest.approx(rng["min"]["vnd"] / 1e6)


async def test_search_majors_no_match_has_hint_and_field_filter_works(env: Env) -> None:
    env.get("/api/v1/majors", "majors_search_cntt.json", params={"search": "cntt"})
    hits = await env.call("search_majors", {"query": "cntt", "field_code": "999"})
    assert hits.structured_content["total_matches"] == 0
    assert "Try a shorter keyword" in hits.structured_content["hint"]
    ok = await env.call("search_majors", {"query": "cntt", "field_code": "748"})
    assert ok.structured_content["total_matches"] == 1


@pytest.mark.parametrize(
    "args", [{"query": "a"}, {"query": "x" * 81}, {"query": "ok", "limit": 99}]
)
async def test_search_majors_rejects_bad_arguments(
    env: Env, args: dict[str, Any]
) -> None:
    r = await env.call("search_majors", args)
    assert r.is_error


async def test_search_schools_lists_all_and_truncates(env: Env) -> None:
    env.get("/api/v1/schools", "schools.json")
    listing = (await env.call("search_schools", {"limit": 5})).structured_content
    total = len(load_fixture("schools.json"))
    assert (listing["total_matches"], listing["returned"]) == (total, 5)
    assert listing["truncated"] is True


async def test_search_schools_query_and_city_filter(env: Env) -> None:
    env.get("/api/v1/schools", "schools_search_bach_khoa.json")
    found = (
        await env.call("search_schools", {"query": "bach khoa"})
    ).structured_content
    s = found["schools"][0]
    assert s["slug"] == "dh-bach-khoa-tphcm" and s["city"] == "HCM"
    assert s["year1_min_dai_tra"]["vnd"] <= s["year1_median_dai_tra"]["vnd"]
    assert s["year1_median_dai_tra"]["vnd"] <= s["year1_max_dai_tra"]["vnd"]

    other_city = await env.call("search_schools", {"query": "bach khoa", "city": "HN"})
    assert other_city.structured_content["total_matches"] == 0
    assert other_city.structured_content["hint"]


# ── get_major_tuition ───────────────────────────────────────────────────────
async def test_get_major_tuition_matches_backend_numbers(env: Env) -> None:
    env.get(HCMUT, "detail_hcmut_khmt.json")
    r = await env.call(
        "get_major_tuition",
        {"school_slug": "dh-bach-khoa-tphcm", "major_slug": "khoa-hoc-may-tinh"},
    )
    assert not r.is_error
    d = r.structured_content
    be = load_fixture("detail_hcmut_khmt.json")
    assert len(d["programs"]) == len(be["programs"]) == 5
    assert len({p["program"]["program_id"] for p in d["programs"]}) == 5
    for got, want in zip(d["programs"], be["programs"], strict=True):
        assert got["year1"]["amount"]["vnd"] == want["year1"]["amountPerYear"]
        assert got["total_course"]["vnd"] == want["totalCourse"]
        assert got["year1"]["source"]["url"] == want["year1"]["source"]["url"]
        assert got["year1"]["academic_year"] == want["year1"]["academicYear"]
    # Hai chuong trinh CLC cung he: phai phan biet duoc bang nhan.
    clc = [p for p in d["programs"] if p["program"]["track"] == "chat_luong_cao"]
    assert len(clc) == 2 and clc[0]["program"]["label"] != clc[1]["program"]["label"]
    # Nam 1 la so cong bo, cac nam sau la du phong.
    first = d["programs"][0]["yearly"]
    assert first[0]["is_projected"] is False and all(
        y["is_projected"] for y in first[1:]
    )
    assert (
        d["web_url"] == "https://hocphi.info/nganh/dh-bach-khoa-tphcm/khoa-hoc-may-tinh"
    )
    assert d["major"]["official_code"] == "7480101" and d["disclaimer"]
    assert len(json.dumps(d, ensure_ascii=False)) < 20_000


async def test_get_major_tuition_states_default_estimate_assumption(env: Env) -> None:
    env.get(HCMUT, "detail_hcmut_khmt.json")
    d = (
        await env.call(
            "get_major_tuition",
            {"school_slug": "dh-bach-khoa-tphcm", "major_slug": "khoa-hoc-may-tinh"},
        )
    ).structured_content
    a = d["programs"][0]["assumptions"]
    assert a["increase_source"] == "default_estimate" and a["standard_years"] == 4
    assert a["annual_increase_pct"] == pytest.approx(10.0, abs=0.5)
    assert "projections" in a["note"]


async def test_get_major_tuition_not_found_is_a_helpful_error(env: Env) -> None:
    env.router.get(UIT).respond(404, json={"detail": "Program not found"})
    r = await env.call(
        "get_major_tuition", {"school_slug": "uit", "major_slug": "khoa-hoc-may-tinh"}
    )
    assert r.is_error
    text = _err_text(r)
    assert "not_found:" in text and "search_majors" in text
    assert "/api/v1" not in text  # khong lo duong dan noi bo


@pytest.mark.parametrize("bad", ["../x", "A B", "", "x" * 81])
async def test_get_major_tuition_rejects_bad_slugs(env: Env, bad: str) -> None:
    r = await env.call(
        "get_major_tuition", {"school_slug": bad, "major_slug": "khoa-hoc-may-tinh"}
    )
    assert r.is_error


async def test_upstream_down_is_a_retryable_error(env: Env) -> None:
    env.router.get(HCMUT).respond(503)
    r = await env.call(
        "get_major_tuition",
        {"school_slug": "dh-bach-khoa-tphcm", "major_slug": "khoa-hoc-may-tinh"},
    )
    assert r.is_error and "upstream_unavailable:" in _err_text(r)


# ── compare_programs ────────────────────────────────────────────────────────
def _item(school: str, track: str = "dai_tra", **kw: Any) -> dict[str, Any]:
    return {
        "school_slug": school,
        "major_slug": "khoa-hoc-may-tinh",
        "track": track,
        **kw,
    }


async def test_compare_sorts_by_year1_notes_mixed_years_and_lists_missing(
    env: Env,
) -> None:
    _all_details(env)
    r = await env.call(
        "compare_programs",
        {
            "items": [
                _item("hutech"),
                _item("dh-bach-khoa-tphcm"),
                _item("dh-quoc-te-tphcm"),
                _item("uit"),
            ]
        },
    )
    assert not r.is_error
    d = r.structured_content
    assert [x["school"]["slug"] for x in d["rows"]] == [
        "dh-bach-khoa-tphcm",
        "dh-quoc-te-tphcm",
        "hutech",
    ]
    vnds = [x["year1"]["amount"]["vnd"] for x in d["rows"]]
    assert vnds == sorted(vnds)
    assert [(x["school_slug"], x["reason"]) for x in d["missing"]] == [
        ("uit", "not_found")
    ]
    assert any("different academic years" in n for n in d["notes"])
    assert {x["year1"]["academic_year"] for x in d["rows"]} == {
        "2025-2026",
        "2026-2027",
    }


async def test_compare_lists_all_programs_of_a_track_and_says_so(env: Env) -> None:
    _all_details(env)
    d = (
        await env.call(
            "compare_programs",
            {"items": [_item("dh-bach-khoa-tphcm", "chat_luong_cao"), _item("hutech")]},
        )
    ).structured_content
    clc_rows = [r for r in d["rows"] if r["program"]["track"] == "chat_luong_cao"]
    assert len(clc_rows) == 2
    assert any("program_id" in n for n in d["notes"])
    assert d["missing"] == []


async def test_compare_reports_missing_track_and_unknown_program_id(env: Env) -> None:
    _all_details(env)
    d = (
        await env.call(
            "compare_programs",
            {
                "items": [
                    _item("hutech", "quoc_te"),
                    _item("dh-bach-khoa-tphcm", program_id="not-a-real-id"),
                    _item("dh-quoc-te-tphcm"),
                ]
            },
        )
    ).structured_content
    reasons = {m["school_slug"]: m for m in d["missing"]}
    assert reasons["hutech"]["reason"] == "no_program_for_track"
    assert reasons["hutech"]["available_tracks"] == ["dai_tra"]
    assert reasons["dh-bach-khoa-tphcm"]["reason"] == "program_not_found"
    assert len(d["rows"]) == 1


async def test_compare_survives_one_upstream_failure(env: Env) -> None:
    env.get(HCMUT, "detail_hcmut_khmt.json")
    env.router.get(HUTECH).respond(503)
    d = (
        await env.call(
            "compare_programs",
            {"items": [_item("dh-bach-khoa-tphcm"), _item("hutech")]},
        )
    ).structured_content
    assert len(d["rows"]) == 1
    assert d["missing"][0]["reason"] == "upstream_unavailable"


async def test_compare_with_nothing_found_is_an_error_and_validates_size(
    env: Env,
) -> None:
    env.router.get(UIT).respond(404)
    env.router.get("/api/v1/schools/hutech/majors/khoa-hoc-may-tinh").respond(404)
    r = await env.call("compare_programs", {"items": [_item("uit"), _item("hutech")]})
    assert r.is_error and "None of the requested programs has data" in _err_text(r)
    assert (await env.call("compare_programs", {"items": [_item("uit")]})).is_error
    five = [_item(f"s{i}") for i in range(5)]
    assert (await env.call("compare_programs", {"items": five})).is_error


async def test_compare_ignores_duplicates(env: Env) -> None:
    _all_details(env)
    d = (
        await env.call(
            "compare_programs",
            {"items": [_item("hutech"), _item("hutech"), _item("dh-quoc-te-tphcm")]},
        )
    ).structured_content
    assert len(d["rows"]) == 2 and any("Duplicate" in n for n in d["notes"])


# ── estimate_total_cost ─────────────────────────────────────────────────────
async def test_estimate_total_cost_reports_backend_total_and_assumptions(
    env: Env,
) -> None:
    env.get(HCMUT, "detail_hcmut_khmt.json")
    d = (
        await env.call(
            "estimate_total_cost",
            {"school_slug": "dh-bach-khoa-tphcm", "major_slug": "khoa-hoc-may-tinh"},
        )
    ).structured_content
    be = load_fixture("detail_hcmut_khmt.json")["programs"][0]
    assert len(d["programs"]) == 1 and be["program"]["track"] == "dai_tra"
    assert d["programs"][0]["total_course"]["vnd"] == be["totalCourse"]
    assert "146.191" in d["summary"][0] and "default estimate" in d["summary"][0]


async def test_estimate_total_cost_track_and_program_id_selection(env: Env) -> None:
    env.get(HCMUT, "detail_hcmut_khmt.json")
    both = (
        await env.call(
            "estimate_total_cost",
            {
                "school_slug": "dh-bach-khoa-tphcm",
                "major_slug": "khoa-hoc-may-tinh",
                "track": "chat_luong_cao",
            },
        )
    ).structured_content
    assert len(both["programs"]) == 2 and len(both["summary"]) == 2
    one_id = both["programs"][0]["program"]["program_id"]
    one = (
        await env.call(
            "estimate_total_cost",
            {
                "school_slug": "dh-bach-khoa-tphcm",
                "major_slug": "khoa-hoc-may-tinh",
                "program_id": one_id,
            },
        )
    ).structured_content
    assert [p["program"]["program_id"] for p in one["programs"]] == [one_id]


async def test_estimate_total_cost_unknown_track_lists_available(env: Env) -> None:
    env.get(HUTECH, "detail_hutech_khmt.json")
    r = await env.call(
        "estimate_total_cost",
        {
            "school_slug": "hutech",
            "major_slug": "khoa-hoc-may-tinh",
            "track": "quoc_te",
        },
    )
    assert r.is_error and "Available tracks: dai_tra" in _err_text(r)


# ── explore_major_taxonomy / find_related_majors ────────────────────────────
async def test_explore_roots_and_node(env: Env) -> None:
    env.get("/api/v1/taxonomy", "taxonomy_roots.json")
    roots = (await env.call("explore_major_taxonomy", {})).structured_content
    assert len(roots["children"]) == 20 and roots["unclassified"]["n_majors"] > 0
    assert roots["code"] is None and roots["hint"]

    env.get("/api/v1/taxonomy/748", "taxonomy_748.json")
    node = (
        await env.call("explore_major_taxonomy", {"code": "748"})
    ).structured_content
    assert node["code"] == "748" and node["level"] == 1
    assert [c["code"] for c in node["children"]] == ["74801", "74802"]
    assert node["majors"] and node["majors_truncated"] is False


async def test_explore_unclassified_and_bad_or_unknown_code(env: Env) -> None:
    env.get("/api/v1/taxonomy/unclassified", "taxonomy_unclassified.json")
    d = (
        await env.call("explore_major_taxonomy", {"code": "unclassified"})
    ).structured_content
    assert d["level"] == 0 and d["path"] == []
    env.router.get("/api/v1/taxonomy/999").respond(404, json={"detail": "nope"})
    unknown = await env.call("explore_major_taxonomy", {"code": "999"})
    assert unknown.is_error and "not_found:" in _err_text(unknown)
    assert (await env.call("explore_major_taxonomy", {"code": "74"})).is_error


async def test_find_related_majors_excludes_itself(env: Env) -> None:
    env.get("/api/v1/majors", "majors_khmt_subset.json")
    env.get("/api/v1/taxonomy/74801", "taxonomy_74801.json")
    d = (
        await env.call("find_related_majors", {"major_slug": "khoa-hoc-may-tinh"})
    ).structured_content
    assert d["group"]["code"] == "74801"
    slugs = [x["slug"] for x in d["related"]]
    assert "khoa-hoc-may-tinh" not in slugs and slugs
    # Nhat quan voi `relatedMajors` cua BE cho cung nganh (nhom + he dai tra).
    be_related = {
        x["slug"] for x in load_fixture("detail_hcmut_khmt.json")["relatedMajors"]
    }
    assert be_related <= set(slugs)


async def test_find_related_majors_unknown_slug_is_a_helpful_error(env: Env) -> None:
    env.get("/api/v1/majors", "majors_khmt_subset.json")
    r = await env.call("find_related_majors", {"major_slug": "khong-ton-tai"})
    assert r.is_error and "search_majors" in _err_text(r)


async def test_find_related_majors_for_an_unclassified_major(env: Env) -> None:
    rows = load_fixture("majors_khmt_subset.json")
    for row in rows:
        row["major"]["taxonomy"] = None
        row["major"]["code"] = None
    env.router.get("/api/v1/majors").respond(200, json=rows)
    d = (
        await env.call("find_related_majors", {"major_slug": "khoa-hoc-may-tinh"})
    ).structured_content
    assert d["group"] is None and d["related"] == [] and "not classified" in d["note"]


# ── Nhat ky ─────────────────────────────────────────────────────────────────
async def test_each_call_logs_a_tool_call_event(env: Env) -> None:
    env.get(HCMUT, "detail_hcmut_khmt.json")
    env.router.get(UIT).respond(404)
    with capture_logs() as logs:
        await env.call(
            "get_major_tuition",
            {"school_slug": "dh-bach-khoa-tphcm", "major_slug": "khoa-hoc-may-tinh"},
        )
        await env.call(
            "get_major_tuition",
            {"school_slug": "uit", "major_slug": "khoa-hoc-may-tinh"},
        )
    events = [e for e in logs if e["event"] == "tool_call"]
    assert [(e["tool"], e["n_results"], e["error_code"]) for e in events] == [
        ("get_major_tuition", 5, None),
        ("get_major_tuition", None, "not_found"),
    ]
    assert all(isinstance(e["duration_ms"], int) for e in events)
