"""search_majors, search_schools — buoc dau: tim slug de goi cac tool khac."""

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from hocphi_mcp import api_models as api
from hocphi_mcp import models as m
from hocphi_mcp.tools.common import (
    STATS_TRACK,
    Deps,
    amount,
    amount_range,
    field_code_of,
    major_ref,
    read_only_tool,
    school_brief,
    tool_call,
)

MAX_SCHOOLS_PER_MAJOR = 8


def _group_by_major(rows: list[api.MajorRowOut]) -> dict[str, list[api.MajorRowOut]]:
    grouped: dict[str, list[api.MajorRowOut]] = {}
    for row in rows:
        grouped.setdefault(row.major.slug, []).append(row)
    return grouped


def _major_hit(rows: list[api.MajorRowOut], deps: Deps) -> m.MajorHit:
    mj = rows[0].major
    ref = major_ref(mj)
    schools: dict[str, api.SchoolOut] = {}
    for r in rows:
        schools.setdefault(r.school.slug, r.school)
    dai_tra = [r.year1.amount_per_year for r in rows if r.program.track == STATS_TRACK]
    return m.MajorHit(
        slug=mj.slug,
        name=mj.name,
        official_code=mj.code,
        field=ref.field,
        group=ref.group,
        aliases=mj.aliases,
        n_schools=len(schools),
        n_programs=len(rows),
        year1_range_dai_tra=amount_range(
            min(dai_tra) if dai_tra else None, max(dai_tra) if dai_tra else None
        ),
        schools=[
            school_brief(s) for s in list(schools.values())[:MAX_SCHOOLS_PER_MAJOR]
        ],
        web_url=deps.major_url(mj.slug),
    )


def register(mcp: MCPServer, deps: Deps) -> None:
    @read_only_tool(mcp, title="Search majors (nganh hoc)")
    async def search_majors(
        query: Annotated[
            str,
            Field(
                min_length=2,
                max_length=80,
                description=(
                    "Major or school name, with or without Vietnamese diacritics, or an "
                    "abbreviation such as 'cntt', 'khmt', 'it' (e.g. 'khoa hoc may tinh')."
                ),
            ),
        ],
        field_code: Annotated[
            str | None,
            Field(
                pattern=r"^(\d{3}|unclassified)$",
                description=(
                    "Optional Ministry field code (3 digits, e.g. '748' = computing) or "
                    "'unclassified'. See explore_major_taxonomy."
                ),
            ),
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=20, description="Max majors returned.")
        ] = 10,
    ) -> m.MajorSearchResult:
        """Find university majors (nganh hoc) in Vietnam by name or alias.

        Returns each matching major once, with how many schools offer it, the year-1
        tuition range for the standard (dai_tra) track, and up to 8 school slugs to use
        with get_major_tuition. Tuition is per year in Vietnamese dong (also in millions).
        Coverage is partial: only schools already collected are included.
        """
        with tool_call("search_majors") as call:
            rows = await deps.api.majors(query)
            if field_code is not None:
                rows = [r for r in rows if field_code_of(r.major) == field_code]
            grouped = _group_by_major(rows)
            hits = sorted(
                (_major_hit(g, deps) for g in grouped.values()),
                key=lambda h: (-h.n_schools, h.name),
            )
            shown = hits[:limit]
            call.n_results = len(shown)
            return m.MajorSearchResult(
                query=query,
                total_matches=len(hits),
                returned=len(shown),
                truncated=len(hits) > len(shown),
                majors=shown,
                hint=None
                if hits
                else (
                    "No major matched. Try a shorter keyword, an abbreviation (cntt, khmt) "
                    "or browse with explore_major_taxonomy. The school or major may also not "
                    "be collected yet."
                ),
            )

    @read_only_tool(mcp, title="Search schools (truong)")
    async def search_schools(
        query: Annotated[
            str | None,
            Field(
                min_length=2,
                max_length=80,
                description="School name or abbreviation (e.g. 'bach khoa', 'hcmut'). Omit to list all.",
            ),
        ] = None,
        city: Annotated[m.CityCode | None, Field(description="HCM or HN.")] = None,
        category: Annotated[
            m.SchoolCategory | None, Field(description="Ownership/autonomy category.")
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=20, description="Max schools returned.")
        ] = 10,
    ) -> m.SchoolSearchResult:
        """Find schools that have tuition data, with their standard-track year-1 range.

        Each school shows how many programs are collected and the min / median / max year-1
        tuition of its standard (dai_tra) programs, per year, in dong and millions.
        """
        with tool_call("search_schools") as call:
            rows = await deps.api.schools(query)
            if city is not None:
                rows = [r for r in rows if r.school.city_code == city]
            if category is not None:
                rows = [r for r in rows if r.school.category == category]
            hits = [
                m.SchoolHit(
                    slug=r.school.slug,
                    name=r.school.name,
                    short_name=r.school.short_name,
                    city=r.school.city_code,
                    category=r.school.category,
                    n_programs=r.stats.n_programs,
                    year1_min_dai_tra=amount(r.stats.min_amount),
                    year1_median_dai_tra=amount(r.stats.median_amount),
                    year1_max_dai_tra=amount(r.stats.max_amount),
                    web_url=deps.school_url(r.school.slug),
                )
                for r in rows
            ]
            shown = hits[:limit]
            call.n_results = len(shown)
            return m.SchoolSearchResult(
                query=query,
                total_matches=len(hits),
                returned=len(shown),
                truncated=len(hits) > len(shown),
                schools=shown,
                hint=None
                if hits
                else "No school matched. Try another spelling, or omit the query to list all.",
            )
