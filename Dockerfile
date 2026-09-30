# Da tang: "build" co uv de cai dependencies + build goi; "runtime" chi chua .venv (goi da
# cai san, KHONG can ma nguon), chay bang user khong phai root. Cung mau voi hocphi-info-be.
#
#   docker build -t hocphi-mcp .
#   docker run --rm -p 8080:8080 -e ALLOWED_HOSTS="localhost:*,127.0.0.1:*" hocphi-mcp
#
# Cloud Run dat $PORT (mac dinh 8080) va ALLOWED_HOSTS/GCP_PROJECT qua bien moi truong.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Cai dependencies truoc (cache theo pyproject.toml + uv.lock), roi moi cai chinh goi.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# --no-editable: cai goi that vao .venv nen runtime khong can thu muc src.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER app
EXPOSE 8080
# Chay python truc tiep tu .venv (khong qua `uv run`) de khoi dong nhanh — quan trong voi
# Cloud Run khi scale tu 0.
CMD ["python", "-m", "hocphi_mcp"]
