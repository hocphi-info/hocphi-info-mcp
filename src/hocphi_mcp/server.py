"""Lap rap MCPServer: cau hinh, huong dan cho mo hinh, dang ky 7 tool."""

from mcp.server.mcpserver import MCPServer

from hocphi_mcp.api_client import HocphiApi
from hocphi_mcp.config import Settings
from hocphi_mcp.tools import search, taxonomy, tuition
from hocphi_mcp.tools.common import Deps

INSTRUCTIONS = """\
Tuition data for Vietnamese universities from hocphi.info (read-only, with sources).

Workflow: use search_majors / search_schools first to get slugs, then get_major_tuition,
compare_programs or estimate_total_cost. explore_major_taxonomy and find_related_majors
help discover majors by area.

Rules for answering:
- Amounts are per academic year in Vietnamese dong (also given in millions).
- Only `year1` is a figure published by the school; later years are PROJECTIONS
  (is_projected=true). Always say which is which.
- Always mention the academic year and the source URL of a figure you quote.
- Each training track (dai_tra standard, chat_luong_cao high-quality, tien_tien advanced,
  quoc_te international), language and campus is a separate program with its own price:
  never average across them.
- Coverage is partial (only schools collected so far). If a tool says there is no data,
  say so plainly; do not guess or use figures from memory.
"""


def build_server(api: HocphiApi, settings: Settings) -> MCPServer:
    mcp = MCPServer("hocphi", instructions=INSTRUCTIONS)
    deps = Deps(api=api, settings=settings)
    search.register(mcp, deps)
    tuition.register(mcp, deps)
    taxonomy.register(mcp, deps)
    return mcp
