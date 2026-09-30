"""Phan dung chung cua cac tool: mapper BE -> model dau ra, loi co ma, log moi lan goi.

Nguyen tac: KHONG tinh lai quy tac hoc phi. Cac ham o day chi doi hinh dang (dong -> trieu,
gom nhom, dat nhan) va gan nguon; moi con so goc do BE tinh.
"""

import inspect
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from hocphi_mcp import api_models as api
from hocphi_mcp import models as m
from hocphi_mcp.api_client import HocphiApi
from hocphi_mcp.config import Settings
from hocphi_mcp.errors import (
    ApiError,
    BadResponse,
    InvalidArgument,
    NotFound,
    Unavailable,
)

logger = structlog.get_logger("hocphi_mcp.tools")

DISCLAIMER = (
    "Reference figures from the schools' own published announcements (source URL given for "
    "each). Only year 1 is published; later years are projections. Confirm on the school's "
    "website before deciding."
)

TRACK_LABELS = {
    "dai_tra": "Đại trà",
    "chat_luong_cao": "Chất lượng cao",
    "tien_tien": "Tiên tiến",
    "quoc_te": "Quốc tế/liên kết",
}
LANGUAGE_LABELS = {"vi": "Tiếng Việt", "en": "Tiếng Anh", "vi_en": "Song ngữ Việt–Anh"}
STATS_TRACK: m.Track = "dai_tra"  # cung quy tac "khong tron he" cua BE (STATS_TRACK)


READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    idempotent_hint=True,
    destructive_hint=False,
    open_world_hint=False,
)


def read_only_tool(mcp: MCPServer, *, title: str) -> Callable[[Any], Any]:
    """Dang ky tool chi doc. Mo ta = docstring da bo thut le (`inspect.cleandoc`), neu
    khong moi dong tiep noi se mang theo khoang trang thua vao mo ta gui cho LLM."""

    def decorator(fn: Any) -> Any:
        return mcp.tool(
            title=title,
            description=inspect.cleandoc(fn.__doc__ or ""),
            annotations=READ_ONLY,
        )(fn)

    return decorator


@dataclass(frozen=True)
class Deps:
    api: HocphiApi
    settings: Settings

    def school_url(self, slug: str) -> str:
        return f"{self.settings.web_base_url}/truong/{slug}"

    def program_url(self, school_slug: str, major_slug: str) -> str:
        return f"{self.settings.web_base_url}/nganh/{school_slug}/{major_slug}"

    def major_url(self, major_slug: str) -> str:
        return f"{self.settings.web_base_url}/nganh?major={major_slug}"


# ── Loi co ma + log moi lan goi ─────────────────────────────────────────────
ErrorCode = Literal[
    "not_found", "invalid_argument", "upstream_unavailable", "internal_error"
]


class ToolFailure(ToolError):
    """Loi da luong truoc: SDK tra `is_error=True` va model doc duoc `message`."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code: ErrorCode = code


@dataclass
class CallInfo:
    tool: str
    n_results: int | None = None
    error_code: str | None = None


@contextmanager
def tool_call(name: str, *, not_found_hint: str = "") -> Iterator[CallInfo]:
    """Boc than tool: doi `ApiError` thanh `ToolFailure` va ghi mot su kien `tool_call`."""
    info = CallInfo(name)
    started = time.monotonic()
    try:
        yield info
    except ToolFailure as exc:
        info.error_code = exc.code
        raise
    except NotFound as exc:
        info.error_code = "not_found"
        raise ToolFailure(
            "not_found", f"Nothing found for this request. {not_found_hint}".strip()
        ) from exc
    except InvalidArgument as exc:
        info.error_code = "invalid_argument"
        raise ToolFailure("invalid_argument", str(exc)) from exc
    except Unavailable as exc:
        info.error_code = "upstream_unavailable"
        raise ToolFailure(
            "upstream_unavailable",
            f"{exc} This is temporary; retrying in a few minutes usually works.",
        ) from exc
    except (BadResponse, ApiError) as exc:
        info.error_code = "internal_error"
        raise ToolFailure(
            "internal_error",
            "The data service returned something unexpected. Please try again later.",
        ) from exc
    except BaseException:
        info.error_code = "internal_error"
        raise
    finally:
        logger.info(
            "tool_call",
            tool=name,
            duration_ms=round((time.monotonic() - started) * 1000),
            n_results=info.n_results,
            error_code=info.error_code,
        )


# ── Mapper ──────────────────────────────────────────────────────────────────
def amount(vnd: int | float) -> m.Amount:
    vnd = round(vnd)
    return m.Amount(vnd=vnd, million=round(vnd / 1_000_000, 3))


def amount_range(lo: int | None, hi: int | None) -> m.AmountRange | None:
    if lo is None or hi is None:
        return None
    return m.AmountRange(min=amount(lo), max=amount(hi))


def school_brief(s: api.SchoolOut) -> m.SchoolBrief:
    return m.SchoolBrief(slug=s.slug, name=s.name, short_name=s.short_name)


def school_ref(s: api.SchoolOut, deps: Deps) -> m.SchoolRef:
    return m.SchoolRef(
        slug=s.slug,
        name=s.name,
        short_name=s.short_name,
        web_url=deps.school_url(s.slug),
    )


def major_ref(mj: api.MajorOut) -> m.MajorRef:
    tax = mj.taxonomy
    return m.MajorRef(
        slug=mj.slug,
        name=mj.name,
        official_code=mj.code,
        field=m.NodeRef(code=tax.field.code, name=tax.field.name) if tax else None,
        group=m.NodeRef(code=tax.group.code, name=tax.group.name) if tax else None,
    )


def field_code_of(mj: api.MajorOut) -> str:
    """Ma linh vuc cua nganh, hoac 'unclassified' (cung quy uoc voi API/FE)."""
    return mj.taxonomy.field.code if mj.taxonomy else "unclassified"


def program_info(p: api.ProgramOut) -> m.ProgramInfo:
    parts = [TRACK_LABELS[p.track], LANGUAGE_LABELS[p.language]]
    if p.campus:
        parts.append(p.campus)
    return m.ProgramInfo(
        program_id=p.id,
        track=p.track,
        language=p.language,
        campus=p.campus,
        display_name=p.display_name,
        label=" · ".join(parts),
    )


def source_ref(s: api.SourceOut | None) -> m.SourceRef | None:
    if s is None:
        return None
    return m.SourceRef(
        url=s.url,
        doc_type=s.doc_type,
        published_date=s.published_date.isoformat() if s.published_date else None,
    )


def year1(t: api.TuitionRecordOut) -> m.Year1:
    return m.Year1(
        academic_year=t.academic_year,
        amount=amount(t.amount_per_year),
        confidence=t.confidence,
        source=source_ref(t.source),
    )


def assumptions(d: api.ProgramDetailOut, standard_years: int) -> m.Assumptions:
    """Gia dinh cua BE. BE chi tra `increase` khi truong cong bo lo trinh; neu khong, no
    dung muc mac dinh nhung KHONG tra ve — ta chi rut % ngam dinh tu chinh cac so nam cua
    BE (ty le nam 2/nam 1), khong ap mot quy tac nao."""
    yearly = d.yearly_amounts
    implied = (
        round((yearly[1].amount_per_year / yearly[0].amount_per_year - 1) * 100, 1)
        if len(yearly) >= 2 and yearly[0].amount_per_year > 0
        else 0.0
    )
    if d.increase is not None:
        pct = d.increase.annual_increase_pct
        source: m.IncreaseSource = d.increase.increase_source
    else:
        pct, source = implied, "default_estimate"
    if source == "published_roadmap":
        note = (
            f"Later years follow the school's published roadmap (about +{pct}%/year)."
        )
    else:
        note = (
            "The school has not published a tuition roadmap, so later years use a default "
            f"estimate of about +{pct}%/year. These are projections, not published figures."
        )
    return m.Assumptions(
        standard_years=standard_years,
        annual_increase_pct=pct,
        increase_source=source,
        note=note,
    )


def program_tuition(d: api.ProgramDetailOut, standard_years: int) -> m.ProgramTuition:
    extra = d.total_with_license - d.total_course
    return m.ProgramTuition(
        program=program_info(d.program),
        year1=year1(d.year1),
        yearly=[
            m.YearAmount(
                academic_year=y.academic_year,
                amount=amount(y.amount_per_year),
                is_projected=y.is_projected,
            )
            for y in d.yearly_amounts
        ],
        total_course=amount(d.total_course),
        additional_professional_costs=amount(extra) if extra > 0 else None,
        assumptions=assumptions(d, standard_years),
    )
