"""Goi API THAT qua HocphiApi de doi chieu bang mat (khong nam trong CI/pytest).

uv run python scripts/smoke_real_api.py
"""

import asyncio

from hocphi_mcp.api_client import HocphiApi
from hocphi_mcp.config import Settings
from hocphi_mcp.errors import NotFound


async def main() -> None:
    settings = Settings()
    api = HocphiApi(settings)
    try:
        roots = await api.taxonomy_roots()
        print(f"[{settings.api_base_url}] linh vuc co du lieu: {len(roots.fields)}")

        d = await api.program_detail("dh-bach-khoa-tphcm", "khoa-hoc-may-tinh")
        print(f"KHMT-HCMUT: {len(d.programs)} chuong trinh")
        for p in d.programs:
            print(
                f"  {p.program.track:15} {p.program.language:6} "
                f"{p.year1.amount_per_year:>12,} d  {p.year1.academic_year}  "
                f"{p.year1.source.url if p.year1.source else '-'}"
            )

        rows = await api.majors("cntt")
        print(f"search=cntt -> {len(rows)} dong, alias={rows[0].major.aliases}")

        try:
            await api.program_detail("uit", "khoa-hoc-may-tinh")
        except NotFound as exc:
            print(f"UIT-KHMT -> NotFound (dung ky vong): {exc}")

        node = await api.taxonomy_node("748")
        print(f"taxonomy 748: {[c.code for c in node.children]}")
    finally:
        await api.aclose()


if __name__ == "__main__":
    asyncio.run(main())
