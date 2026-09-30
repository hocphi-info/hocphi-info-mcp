# hocphi-info-mcp

Public, **read-only** [MCP](https://modelcontextprotocol.io) server for
[hocphi.info](https://hocphi.info) — Vietnamese university tuition data with sources.
Lets an AI assistant look up and compare tuition by school and major and get the **same
numbers as the website**, with the academic year and source, instead of guessing.

> **Status: work in progress.** This repo currently contains the foundation only
> (typed API client, models generated from the backend's OpenAPI, CI). The MCP tools,
> HTTP server and Cloud Run deployment land in the next steps.

## How it works

The server is a thin client of the public hocphi API (`hocphi-info-be`). It contains **no
tuition rules of its own**: every figure (year 1, projected years, course total, ranges)
is computed by the backend; this repo only fetches, validates, caches and presents them
with their sources. It never touches the database.

```
AI client ──MCP (Streamable HTTP)──▶ hocphi-mcp (Cloud Run) ──HTTPS──▶ hocphi API (Fly) ──▶ Postgres
```

## Develop

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you).

```bash
make install     # uv sync
make check       # ruff + mypy + generated-models check + pytest (same as CI)
make gen-models  # regenerate src/hocphi_mcp/api_models.py from the backend OpenAPI
uv run python scripts/smoke_real_api.py   # call the real API through the client
```

- `src/hocphi_mcp/api_models.py` is **generated** from the backend's `openapi.json`
  (`main` of `hocphi-info-be`); never edit it by hand. Set `OPENAPI_SRC=../hocphi-info-be/openapi.json`
  to develop against a local backend spec. CI regenerates it and fails on any diff, and runs
  daily, so a backend contract change is noticed even when this repo has no commits.
- Configuration is via environment variables (see `.env.example`); defaults are production-ready.
- By default the client calls the Fly origin (`https://hocphi-info-api.fly.dev`) rather than
  `api.hocphi.info`: the latter is behind Cloudflare, which blocks some User-Agents, and
  server-to-server traffic does not need that layer.

## License / data

Tuition figures come from public school announcements; each one carries its source URL.
Treat them as reference values and confirm on the school's website.
