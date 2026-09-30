"""explore_major_taxonomy, find_related_majors — duyet cay Linh vuc -> Nhom nganh -> Nganh."""

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from hocphi_mcp import api_models as api
from hocphi_mcp import models as m
from hocphi_mcp.tools.common import (
    Deps,
    ToolFailure,
    amount_range,
    major_ref,
    read_only_tool,
    tool_call,
)

MAX_MAJORS_IN_VIEW = 30
MAX_RELATED = 6


def _major_summary(x: api.TaxonomyMajorOut) -> m.MajorSummary:
    return m.MajorSummary(
        slug=x.slug,
        name=x.name,
        official_code=x.code,
        n_schools=x.n_schools,
        year1_range_dai_tra=amount_range(x.min_year1_amount, x.max_year1_amount),
    )


def _child(c: api.TaxonomyChildOut) -> m.TaxonomyChild:
    return m.TaxonomyChild(
        code=c.code,
        name=c.name,
        level=c.level,
        n_majors=c.n_majors,
        n_programs=c.n_programs,
    )


def register(mcp: MCPServer, deps: Deps) -> None:
    @read_only_tool(mcp, title="Explore the Ministry major taxonomy")
    async def explore_major_taxonomy(
        code: Annotated[
            str | None,
            Field(
                pattern=r"^(\d{3}|\d{5}|\d{7}|unclassified)$",
                description=(
                    "Ministry code: 3 digits = field (linh vuc), 5 = group (nhom nganh), "
                    "7 = major (nganh), or 'unclassified'. Omit to list all fields."
                ),
            ),
        ] = None,
    ) -> m.TaxonomyView:
        """Browse Vietnam's Ministry of Education major classification (with data only).

        Without `code`: the fields that have tuition data, plus how many majors are
        unclassified. With a code: its path from the top, its children (with counts) and
        the majors below it (with school counts and standard-track year-1 range). Use it to
        discover majors by area (e.g. code '748' = computing and IT).
        """
        with tool_call(
            "explore_major_taxonomy",
            not_found_hint="Start without a code to list valid fields, then go deeper.",
        ) as call:
            if code is None:
                roots = await deps.api.taxonomy_roots()
                call.n_results = len(roots.fields)
                return m.TaxonomyView(
                    code=None,
                    name=None,
                    level=None,
                    path=[],
                    n_majors=None,
                    n_programs=None,
                    children=[_child(c) for c in roots.fields],
                    majors=[],
                    majors_truncated=False,
                    unclassified=m.UnclassifiedSummary(
                        n_majors=roots.unclassified.n_majors,
                        n_programs=roots.unclassified.n_programs,
                    )
                    if roots.unclassified
                    else None,
                    hint="Call again with a field code (e.g. '748') to see its groups and majors.",
                )
            node = await deps.api.taxonomy_node(code)
            shown = node.majors[:MAX_MAJORS_IN_VIEW]
            call.n_results = len(shown)
            return m.TaxonomyView(
                code=node.code,
                name=node.name,
                level=node.level,
                path=[m.NodeRef(code=n.code, name=n.name) for n in node.path],
                n_majors=node.n_majors,
                n_programs=node.n_programs,
                children=[_child(c) for c in node.children],
                majors=[_major_summary(x) for x in shown],
                majors_truncated=len(node.majors) > len(shown),
                hint="Use a major's slug with search_majors, then get_major_tuition.",
            )

    @read_only_tool(mcp, title="Find related majors")
    async def find_related_majors(major_slug: m.Slug) -> m.RelatedMajorsResult:
        """Find majors in the same Ministry group as the given major, for comparison.

        Returns up to 6 related majors that have tuition data, each with the number of
        schools and the standard-track year-1 range. Majors without a Ministry
        classification have no group, so the list is empty for them.
        """
        with tool_call(
            "find_related_majors",
            not_found_hint="Find the major's slug with search_majors first.",
        ) as call:
            rows = await deps.api.majors()
            match = next((r.major for r in rows if r.major.slug == major_slug), None)
            if match is None:
                raise ToolFailure(
                    "not_found",
                    f"No major with slug '{major_slug}' has tuition data. "
                    "Find the slug with search_majors.",
                )
            ref = major_ref(match)
            if match.taxonomy is None or ref.group is None:
                call.n_results = 0
                return m.RelatedMajorsResult(
                    major=ref,
                    group=None,
                    related=[],
                    note="This major is not classified in the Ministry list, so it has no "
                    "group to compare within.",
                )
            node = await deps.api.taxonomy_node(ref.group.code)
            related = [_major_summary(x) for x in node.majors if x.slug != major_slug]
            shown = related[:MAX_RELATED]
            call.n_results = len(shown)
            return m.RelatedMajorsResult(
                major=ref,
                group=ref.group,
                related=shown,
                note=None
                if shown
                else "No other major in this group has tuition data yet.",
            )
