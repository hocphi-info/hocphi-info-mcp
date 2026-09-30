# Project: hocphi-info-mcp

Public **read-only** MCP server for [hocphi.info](https://hocphi.info) tuition data. Sibling repos:
`hocphi-info-be` (FastAPI, the source of every number) and `hocphi-info-fe` (Next.js site).

Owner is learning MCP and GCP while building this (background: Go/Flutter/FastAPI). Prefer plain,
idiomatic Python over clever abstractions, and explain the concept when introducing one.

## Architecture

- **This server is a client of the public REST API — it never touches the database and never
  recomputes tuition.** Year-1 amount, projected years, course total, min/max ranges are all
  computed by the backend; we only fetch, validate, cache and present them with sources. A second
  copy of a rule would drift from the website.
- Tools are read-only. No write tools, no LLM calls, no secrets at runtime.
- Errors from the API are turned into typed errors (`errors.py`); no `httpx` exception leaks out
  of `api_client.py`.

## Folder structure

```
src/hocphi_mcp/
  config.py       # pydantic-settings (env vars, defaults are production-ready)
  errors.py       # NotFound / Unavailable / InvalidArgument / BadResponse
  cache.py        # TTL cache + single-flight
  api_client.py   # HocphiApi: retry, timeout, cache, schema validation
  api_models.py   # GENERATED from the backend openapi.json — never hand-edit
  logging.py      # structlog JSON (Cloud Logging severity/message)
  models.py       # hand-written tool output models (LLM-facing descriptions)
  server.py       # MCPServer + instructions for the model, registers the 7 tools
  tools/          # common.py (mappers, ToolFailure, tool_call log scope), search.py,
                  #   tuition.py (get/compare/estimate), taxonomy.py (explore/related)
scripts/          # gen_models.sh, smoke_real_api.py
tests/            # respx fakes the backend; fixtures/ hold real API responses
```

## Conventions

- `api_models.py` is generated: change the backend model, `make openapi` there, then `make gen-models` here.
  `make gen-check` (and CI, plus a daily cron) fail when it is out of date.
- Tool output models (`models.py`) are hand-written and separate from the generated parsing models.
- Tool descriptions, field descriptions and errors are for the **LLM**: keep them in English, short,
  and concrete (tell it the next tool to call). Data values (names) stay Vietnamese.
- Failures the model should read are raised as `ToolFailure(code, message)` (a `ToolError`): the SDK
  returns `is_error=True` with that text. Any other exception is a crash (generic message + traceback log).
- Tests call tools through the in-memory `mcp.Client` against a `respx`-faked backend. Do not keep
  a `Client` in an async pytest fixture (anyio cancel-scope error): open it per call.
- Tooling: `uv`, `ruff` (lint+format), `mypy` (`disallow_untyped_defs`), `pytest` (async).
  Run `make check` before committing.
- The API is behind Cloudflare (some User-Agents get 403); default `API_BASE_URL` is the Fly origin
  and the client always sends an explicit `User-Agent`.

## Git commit messages

Always in English, regardless of the conversation language. No AI-attribution lines
(no "Generated with Claude", no Co-Authored-By Claude) in commits or PR descriptions.
