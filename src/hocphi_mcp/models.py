"""Model DAU RA (va dau vao phuc tap) cua cac tool — viet tay, gon, co mo ta cho LLM.

Khac `api_models.py` (SINH tu openapi.json, chi de doc response cua BE): o day ta chon
nhung gi mo hinh nhin thay. Nguyen tac:
- Moi so tien co ca dong (`vnd`) va trieu dong (`million`) de AI khong nham don vi.
- Nam dau (`year1`) la so DA CONG BO kem nguon; cac nam sau la DU PHONG (`is_projected`).
- Khoa JSON snake_case (nhu tham so vao); ten truong/nganh giu tieng Viet.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Track = Literal["dai_tra", "chat_luong_cao", "tien_tien", "quoc_te"]
Language = Literal["vi", "en", "vi_en"]
Confidence = Literal["verified", "published_unverified", "estimated"]
IncreaseSource = Literal["published_roadmap", "default_estimate"]
DocType = Literal["de_an_tuyen_sinh", "thong_bao_hoc_phi", "quy_dinh_nghe", "khac"]
CityCode = Literal["HCM", "HN"]
SchoolCategory = Literal[
    "cong_lap", "cong_lap_tu_chu", "tu_thuc", "tu_thuc_von_nuoc_ngoai"
]

MissingReason = Literal[
    "not_found",
    "no_program_for_track",
    "program_not_found",
    "upstream_unavailable",
    "invalid_argument",
]

SLUG_PATTERN = r"^[a-z0-9-]{1,80}$"
Slug = Annotated[str, Field(pattern=SLUG_PATTERN, description="Lowercase slug.")]


# ── Khoi dung chung ─────────────────────────────────────────────────────────
class Amount(BaseModel):
    vnd: int = Field(description="Amount in Vietnamese dong.")
    million: float = Field(description="Same amount in million dong (e.g. 31.5).")


class AmountRange(BaseModel):
    min: Amount
    max: Amount


class NodeRef(BaseModel):
    code: str = Field(description="Ministry classification code (3/5/7 digits).")
    name: str


class SchoolBrief(BaseModel):
    slug: str
    name: str
    short_name: str | None = None


class SchoolRef(SchoolBrief):
    web_url: str


class MajorRef(BaseModel):
    slug: str
    name: str
    official_code: str | None = Field(
        default=None, description="7-digit Ministry major code; null if unclassified."
    )
    field: NodeRef | None = Field(
        default=None, description="Ministry field (linh vuc)."
    )
    group: NodeRef | None = Field(
        default=None, description="Ministry group (nhom nganh)."
    )


class SourceRef(BaseModel):
    url: str
    doc_type: DocType
    published_date: str | None = Field(default=None, description="ISO date, if known.")


class ProgramInfo(BaseModel):
    program_id: str
    track: Track
    language: Language
    campus: str | None = Field(default=None, description="null = main campus.")
    display_name: str | None = None
    label: str = Field(
        description="Human-readable distinguisher (track, language, campus)."
    )


class Year1(BaseModel):
    academic_year: str = Field(description='e.g. "2026-2027".')
    amount: Amount = Field(description="Published tuition for this year, per year.")
    confidence: Confidence
    source: SourceRef | None = Field(
        default=None, description="Where the school published this figure."
    )


class YearAmount(BaseModel):
    academic_year: str
    amount: Amount
    is_projected: bool = Field(
        description="true = estimate for a later year, NOT a published figure."
    )


class Assumptions(BaseModel):
    standard_years: int = Field(description="Standard length of the course in years.")
    annual_increase_pct: float = Field(
        description="Annual increase applied to later years (percent)."
    )
    increase_source: IncreaseSource
    note: str


class ProgramTuition(BaseModel):
    program: ProgramInfo
    year1: Year1
    yearly: list[YearAmount] = Field(description="Year 1 (published) then projections.")
    total_course: Amount = Field(description="Estimated total for the standard course.")
    additional_professional_costs: Amount | None = Field(
        default=None, description="Extra licence/practice costs, if the data has any."
    )
    assumptions: Assumptions


# ── Tra ve cua tung tool ────────────────────────────────────────────────────
class MajorHit(BaseModel):
    slug: str
    name: str
    official_code: str | None
    field: NodeRef | None
    group: NodeRef | None
    aliases: list[str]
    n_schools: int
    n_programs: int
    year1_range_dai_tra: AmountRange | None = Field(
        description="Year-1 range over the standard (dai_tra) track; null if none."
    )
    schools: list[SchoolBrief] = Field(
        description="Up to 8 schools, to use as next-call slugs."
    )
    web_url: str


class MajorSearchResult(BaseModel):
    query: str
    total_matches: int
    returned: int
    truncated: bool
    majors: list[MajorHit]
    hint: str | None = None


class SchoolHit(BaseModel):
    slug: str
    name: str
    short_name: str | None
    city: CityCode
    category: SchoolCategory
    n_programs: int
    year1_min_dai_tra: Amount
    year1_median_dai_tra: Amount
    year1_max_dai_tra: Amount
    web_url: str


class SchoolSearchResult(BaseModel):
    query: str | None
    total_matches: int
    returned: int
    truncated: bool
    schools: list[SchoolHit]
    hint: str | None = None


class MajorTuitionResult(BaseModel):
    school: SchoolRef
    major: MajorRef
    programs: list[ProgramTuition]
    web_url: str
    disclaimer: str


class CostEstimateResult(BaseModel):
    school: SchoolRef
    major: MajorRef
    programs: list[ProgramTuition]
    summary: list[str] = Field(description="One plain-language line per program.")
    web_url: str
    disclaimer: str


class CompareItem(BaseModel):
    school_slug: Slug
    major_slug: Slug
    track: Track = Field(default="dai_tra", description="Training track to compare.")
    program_id: str | None = Field(
        default=None,
        max_length=40,
        description="Exact program id (from get_major_tuition) to disambiguate.",
    )


class ComparisonRow(BaseModel):
    school: SchoolRef
    major: MajorRef
    program: ProgramInfo
    year1: Year1
    total_course: Amount
    assumptions: Assumptions
    web_url: str


class MissingItem(BaseModel):
    school_slug: str
    major_slug: str
    reason: MissingReason
    message: str
    available_tracks: list[Track] = Field(default_factory=list)


class ComparisonResult(BaseModel):
    rows: list[ComparisonRow] = Field(
        description="Sorted by year-1 tuition, ascending."
    )
    missing: list[MissingItem]
    notes: list[str]
    disclaimer: str


class TaxonomyChild(BaseModel):
    code: str
    name: str
    level: int
    n_majors: int
    n_programs: int


class MajorSummary(BaseModel):
    slug: str
    name: str
    official_code: str | None
    n_schools: int
    year1_range_dai_tra: AmountRange | None


class UnclassifiedSummary(BaseModel):
    n_majors: int
    n_programs: int
    explore_with: str = "explore_major_taxonomy(code='unclassified')"


class TaxonomyView(BaseModel):
    code: str | None = Field(description="null when listing all fields.")
    name: str | None
    level: int | None = Field(description="0 unclassified, 1 field, 2 group, 3 major.")
    path: list[NodeRef]
    n_majors: int | None
    n_programs: int | None
    children: list[TaxonomyChild]
    majors: list[MajorSummary]
    majors_truncated: bool
    unclassified: UnclassifiedSummary | None = None
    hint: str | None = None


class RelatedMajorsResult(BaseModel):
    major: MajorRef
    group: NodeRef | None
    related: list[MajorSummary]
    note: str | None = None
