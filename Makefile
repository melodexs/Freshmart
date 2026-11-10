.PHONY: help setup dev test lint format build-web check-web clean
API := apps/api
WEB := apps/web

help:  ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

setup:  ## Create the virtualenv and install Python + TypeScript dependencies
	python3 -m venv $(API)/.venv
	$(API)/.venv/bin/pip install -q -r $(API)/requirements-dev.txt
	cd $(WEB) && npm ci

dev:  ## Run the app (API + frontend) at http://localhost:4000
	cd $(API) && .venv/bin/uvicorn app.main:app --reload --port 4000

test:  ## Run the API test suite
	cd $(API) && .venv/bin/python -m pytest -q

lint:  ## Check Python style and type-check the TypeScript
	cd $(API) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(WEB) && npm run typecheck

format:  ## Auto-fix code style
	cd $(API) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

build-web:  ## Compile TypeScript into apps/web/static/js (commit the result)
	cd $(WEB) && npm run build

check-web:  ## Fail if the committed bundle is out of date
	cd $(WEB) && npm run build && git diff --exit-code static/js

clean:  ## Remove caches
	python3 scripts/clean.py
