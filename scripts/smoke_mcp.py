"""Smoke test mot MCP server DANG CHAY (cuc bo, container hoac Cloud Run) bang SDK Client.

    uv run python scripts/smoke_mcp.py http://localhost:8080/mcp            # chi liet ke tool
    uv run python scripts/smoke_mcp.py https://<host>/mcp --call            # them 1 lan goi that

Thoat 0 neu OK, 1 neu sai — dung lai lam buoc smoke test sau khi deploy (U8). Kiem ca giao
thuc cu (`legacy`) lan moi (`auto`). `--call` di den API that (Fly) nen khong dung trong CI.
"""

import argparse
import asyncio
import sys

from mcp import Client

EXPECTED_TOOLS = {
    "search_majors",
    "search_schools",
    "get_major_tuition",
    "compare_programs",
    "estimate_total_cost",
    "explore_major_taxonomy",
    "find_related_majors",
}


async def check(url: str, mode: str, call: bool) -> list[str]:
    problems: list[str] = []
    async with Client(url, mode=mode) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        if names != EXPECTED_TOOLS:
            problems.append(
                f"[{mode}] tools khac ky vong: {sorted(names ^ EXPECTED_TOOLS)}"
            )
        if call:
            r = await client.call_tool("search_majors", {"query": "khmt"})
            majors = (r.structured_content or {}).get("majors", [])
            if r.is_error or not majors:
                problems.append(
                    f"[{mode}] search_majors('khmt') khong co ket qua: {r.content}"
                )
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument(
        "--call", action="store_true", help="goi 1 tool that (can API that)"
    )
    args = parser.parse_args()

    problems: list[str] = []
    for mode in ("legacy", "auto"):
        try:
            problems += await check(args.url, mode, args.call)
        except Exception as exc:
            problems.append(f"[{mode}] {type(exc).__name__}: {exc}")
    for p in problems:
        print("FAIL", p)
    print("OK" if not problems else f"{len(problems)} van de")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
