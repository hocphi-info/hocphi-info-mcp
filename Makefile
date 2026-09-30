# Cac lenh hay dung khi phat trien hocphi-info-mcp. `make` hoac `make help` liet ke.
UV ?= uv run

.DEFAULT_GOAL := help

.PHONY: help
help: ## Hien thi danh sach target
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Cai dependencies (uv sync)
	uv sync

.PHONY: dev
dev: ## Chay may chu MCP o http://localhost:8080/mcp (PORT=... de doi cong)
	$(UV) python -m hocphi_mcp

.PHONY: lint fmt typecheck test check
lint: ## ruff check + format --check
	$(UV) ruff check .
	$(UV) ruff format --check .

fmt: ## ruff format (sua tai cho)
	$(UV) ruff format .

typecheck: ## mypy
	$(UV) mypy src tests

test: ## pytest
	$(UV) pytest -q

check: lint typecheck gen-check test ## lint + mypy + kiem tra model sinh + pytest (giong CI)

.PHONY: gen-models gen-check
gen-models: ## Sinh lai api_models.py tu openapi.json cua BE (OPENAPI_SRC=... de tro file local)
	./scripts/gen_models.sh

gen-check: ## Bao loi neu api_models.py lech hop dong BE tren main (buoc CI)
	./scripts/gen_models.sh
	git diff --exit-code -- src/hocphi_mcp/api_models.py
