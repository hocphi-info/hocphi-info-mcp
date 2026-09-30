"""Model sinh tu openapi.json phai parse duoc response THAT cua BE (tests/fixtures)."""

from pydantic import TypeAdapter

from hocphi_mcp.api_models import (
    MajorRowOut,
    ProgramDetailResponseOut,
    SchoolRowOut,
    TaxonomyNodeDetailOut,
    TaxonomyRootsOut,
)
from tests.conftest import load_fixture


def test_program_detail_has_five_hcmut_programs_with_sources() -> None:
    d = ProgramDetailResponseOut.model_validate(load_fixture("detail_hcmut_khmt.json"))
    assert d.school.short_name == "HCMUT"
    assert len(d.programs) == 5
    assert {p.program.track for p in d.programs} == {
        "dai_tra",
        "chat_luong_cao",
        "tien_tien",
        "quoc_te",
    }
    assert all(p.year1.source is not None for p in d.programs)
    assert d.related_majors and d.major.taxonomy is not None


def test_taxonomy_node_and_roots() -> None:
    node = TaxonomyNodeDetailOut.model_validate(load_fixture("taxonomy_748.json"))
    assert [n.code for n in node.path] == ["748"]
    assert {c.code for c in node.children} == {"74801", "74802"}
    assert node.majors[0].n_schools >= 1

    roots = TaxonomyRootsOut.model_validate(load_fixture("taxonomy_roots.json"))
    assert len(roots.fields) == 20 and roots.unclassified is not None


def test_majors_search_and_schools_lists() -> None:
    rows = TypeAdapter(list[MajorRowOut]).validate_python(
        load_fixture("majors_search_cntt.json")
    )
    assert rows and "cntt" in rows[0].major.aliases
    schools = TypeAdapter(list[SchoolRowOut]).validate_python(
        load_fixture("schools.json")
    )
    assert schools and schools[0].stats.n_programs > 0


def test_unknown_fields_from_a_newer_backend_are_ignored() -> None:
    payload = load_fixture("taxonomy_roots.json")
    payload["someNewField"] = 1
    payload["fields"][0]["anotherNewField"] = {"x": 1}
    assert TaxonomyRootsOut.model_validate(payload).fields[0].code
