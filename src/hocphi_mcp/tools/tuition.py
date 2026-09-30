"""get_major_tuition, compare_programs, estimate_total_cost.

Ba tool cung dua tren chi tiet chuong trinh cua BE (`program_detail`). Moi con so (nam 1,
du phong, tong khoa) do BE tinh; o day chi chon chuong trinh, doi don vi va gan nguon.
"""

import asyncio
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from hocphi_mcp import api_models as api
from hocphi_mcp import models as m
from hocphi_mcp.errors import ApiError, InvalidArgument, NotFound, Unavailable
from hocphi_mcp.tools.common import (
    DISCLAIMER,
    STATS_TRACK,
    Deps,
    ToolFailure,
    assumptions,
    major_ref,
    program_info,
    program_tuition,
    read_only_tool,
    school_ref,
    tool_call,
    year1,
)

COMPARE_CONCURRENCY = 4
NOT_FOUND_HINT = (
    "Check the slugs with search_majors / search_schools: the school may not offer this "
    "major, or its data may not be collected yet."
)


def select_programs(
    detail: api.ProgramDetailResponseOut, track: m.Track, program_id: str | None
) -> list[api.ProgramDetailOut]:
    """Chuong trinh khop `program_id` (neu co) hoac cung `track`."""
    if program_id is not None:
        return [p for p in detail.programs if p.program.id == program_id]
    return [p for p in detail.programs if p.program.track == track]


def _tracks(detail: api.ProgramDetailResponseOut) -> list[m.Track]:
    seen: list[m.Track] = []
    for p in detail.programs:
        if p.program.track not in seen:
            seen.append(p.program.track)
    return seen


def _million(a: m.Amount) -> str:
    return f"{a.million:g}"


def register(mcp: MCPServer, deps: Deps) -> None:
    @read_only_tool(mcp, title="Get tuition of a major at a school")
    async def get_major_tuition(
        school_slug: m.Slug,
        major_slug: m.Slug,
    ) -> m.MajorTuitionResult:
        """Get all tuition programs of one major at one school, with sources.

        Use slugs returned by search_majors / search_schools. Returns every program (each
        training track, language and campus is separate, with its own program_id): the
        published year-1 tuition with academic year, confidence and source URL, projected
        later years (is_projected=true), and the estimated total for the standard course.
        Amounts are per year in Vietnamese dong and in millions.
        """
        with tool_call("get_major_tuition", not_found_hint=NOT_FOUND_HINT) as call:
            detail = await deps.api.program_detail(school_slug, major_slug)
            years = detail.major.standard_years
            call.n_results = len(detail.programs)
            return m.MajorTuitionResult(
                school=school_ref(detail.school, deps),
                major=major_ref(detail.major),
                programs=[program_tuition(p, years) for p in detail.programs],
                web_url=deps.program_url(school_slug, major_slug),
                disclaimer=DISCLAIMER,
            )

    @read_only_tool(mcp, title="Compare tuition of 2-4 programs")
    async def compare_programs(
        items: Annotated[
            list[m.CompareItem],
            Field(
                min_length=2, max_length=4, description="2 to 4 programs to compare."
            ),
        ],
    ) -> m.ComparisonResult:
        """Compare year-1 tuition and estimated course total across 2-4 programs.

        Each item is a school + major (+ optional track, default 'dai_tra', or an exact
        program_id). Rows are sorted by year-1 tuition. Items without data are listed in
        `missing` with a reason instead of failing the whole comparison. Check `notes`:
        figures from different academic years are not directly comparable.
        """
        with tool_call("compare_programs") as call:
            unique: list[m.CompareItem] = []
            notes: list[str] = []
            seen: set[tuple[str, str, str, str | None]] = set()
            for it in items:
                key = (it.school_slug, it.major_slug, it.track, it.program_id)
                if key in seen:
                    notes.append(
                        f"Duplicate item {it.school_slug}/{it.major_slug} ignored."
                    )
                    continue
                seen.add(key)
                unique.append(it)

            sem = asyncio.Semaphore(COMPARE_CONCURRENCY)

            async def load(
                it: m.CompareItem,
            ) -> api.ProgramDetailResponseOut | ApiError:
                async with sem:
                    try:
                        return await deps.api.program_detail(
                            it.school_slug, it.major_slug
                        )
                    except ApiError as exc:
                        return exc

            loaded = await asyncio.gather(*(load(it) for it in unique))

            rows: list[m.ComparisonRow] = []
            missing: list[m.MissingItem] = []
            for it, result in zip(unique, loaded, strict=True):
                if isinstance(result, ApiError):
                    missing.append(_missing_from_error(it, result))
                    continue
                chosen = select_programs(result, it.track, it.program_id)
                if not chosen:
                    missing.append(_missing_no_program(it, result))
                    continue
                if len(chosen) > 1:
                    notes.append(
                        f"{result.school.name} / {result.major.name} has {len(chosen)} "
                        f"programs in this selection (different language or campus); "
                        "all are listed, tell them apart by `program.label` or pass program_id."
                    )
                for p in chosen:
                    rows.append(
                        m.ComparisonRow(
                            school=school_ref(result.school, deps),
                            major=major_ref(result.major),
                            program=program_info(p.program),
                            year1=year1(p.year1),
                            total_course=program_tuition(
                                p, result.major.standard_years
                            ).total_course,
                            assumptions=assumptions(p, result.major.standard_years),
                            web_url=deps.program_url(it.school_slug, it.major_slug),
                        )
                    )

            if not rows:
                raise ToolFailure(
                    "not_found",
                    "None of the requested programs has data. "
                    + " | ".join(
                        f"{x.school_slug}/{x.major_slug}: {x.message}" for x in missing
                    ),
                )

            years = sorted({r.year1.academic_year for r in rows})
            if len(years) > 1:
                notes.append(
                    "Figures are for different academic years "
                    f"({', '.join(years)}), so they are not directly comparable."
                )
            if any(r.year1.confidence == "estimated" for r in rows):
                notes.append(
                    "Some year-1 figures are marked 'estimated', not published."
                )

            rows.sort(key=lambda r: (r.year1.amount.vnd, r.school.name))
            call.n_results = len(rows)
            return m.ComparisonResult(
                rows=rows, missing=missing, notes=notes, disclaimer=DISCLAIMER
            )

    @read_only_tool(mcp, title="Estimate total course cost")
    async def estimate_total_cost(
        school_slug: m.Slug,
        major_slug: m.Slug,
        track: Annotated[
            m.Track, Field(description="Training track; default standard 'dai_tra'.")
        ] = STATS_TRACK,
        program_id: Annotated[
            str | None,
            Field(max_length=40, description="Exact program id, overrides track."),
        ] = None,
    ) -> m.CostEstimateResult:
        """Estimate the total tuition for the whole standard course of a program.

        Presents the backend's own estimate: published year 1 plus projected later years
        over the standard length of the course. It states the assumptions (increase per
        year and whether it comes from a school-published roadmap or a default estimate).
        It cannot take custom years or increase rates.
        """
        with tool_call("estimate_total_cost", not_found_hint=NOT_FOUND_HINT) as call:
            detail = await deps.api.program_detail(school_slug, major_slug)
            chosen = select_programs(detail, track, program_id)
            if not chosen:
                raise ToolFailure(
                    "not_found",
                    f"No program with track '{track}'"
                    + (f" / program_id '{program_id}'" if program_id else "")
                    + f" for this major. Available tracks: {', '.join(_tracks(detail))}.",
                )
            years = detail.major.standard_years
            programs = [program_tuition(p, years) for p in chosen]
            summary = [
                f"{p.program.label}: about {_million(p.total_course)} million VND over "
                f"{years} standard years (year 1 {p.year1.academic_year}: "
                f"{_million(p.year1.amount)} million VND published; later years projected "
                f"at about +{p.assumptions.annual_increase_pct}%/year, "
                f"{p.assumptions.increase_source.replace('_', ' ')})."
                for p in programs
            ]
            call.n_results = len(programs)
            return m.CostEstimateResult(
                school=school_ref(detail.school, deps),
                major=major_ref(detail.major),
                programs=programs,
                summary=summary,
                web_url=deps.program_url(school_slug, major_slug),
                disclaimer=DISCLAIMER,
            )


def _missing_from_error(it: m.CompareItem, exc: ApiError) -> m.MissingItem:
    reason: m.MissingReason
    if isinstance(exc, NotFound):
        reason = "not_found"
        message = (
            "No data for this school/major pair (the school may not offer it, or it is "
            "not collected yet). Check slugs with search_majors / search_schools."
        )
    elif isinstance(exc, InvalidArgument):
        reason, message = "invalid_argument", str(exc)
    elif isinstance(exc, Unavailable):
        reason, message = (
            "upstream_unavailable",
            "Data service temporarily unavailable.",
        )
    else:
        reason, message = "upstream_unavailable", "Unexpected data service response."
    return m.MissingItem(
        school_slug=it.school_slug,
        major_slug=it.major_slug,
        reason=reason,
        message=message,
    )


def _missing_no_program(
    it: m.CompareItem, detail: api.ProgramDetailResponseOut
) -> m.MissingItem:
    if it.program_id is not None:
        return m.MissingItem(
            school_slug=it.school_slug,
            major_slug=it.major_slug,
            reason="program_not_found",
            message=f"program_id '{it.program_id}' does not belong to this school/major.",
            available_tracks=_tracks(detail),
        )
    return m.MissingItem(
        school_slug=it.school_slug,
        major_slug=it.major_slug,
        reason="no_program_for_track",
        message=f"No '{it.track}' program here; choose one of the available tracks.",
        available_tracks=_tracks(detail),
    )
