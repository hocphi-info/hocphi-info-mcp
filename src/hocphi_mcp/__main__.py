"""`python -m hocphi_mcp` — chay may chu (Cloud Run dat $PORT)."""

import uvicorn

from hocphi_mcp.app import create_app
from hocphi_mcp.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.port,
        # Sau TLS-terminating proxy: tin `X-Forwarded-Proto` de redirect ra dung https://.
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,  # da co dong log `request` cua ta
        log_config=None,  # de structlog/logging cua ta quyet dinh dinh dang
    )


if __name__ == "__main__":
    main()
