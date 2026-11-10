.PHONY: help setup dev test lint format clean
API := apps/api

help:  ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

setup:  ## Create the virtualenv and install dependencies
	python3 -m venv $(API)/.venv
	$(API)/.venv/bin/pip install -q -r $(API)/requirements-dev.txt

dev:  ## Run the app (API + frontend) at http://localhost:4000
	cd $(API) && .venv/bin/uvicorn app.main:app --reload --port 4000

test:  ## Run the API test suite
	cd $(API) && .venv/bin/python -m pytest -q

lint:  ## Check code style
	cd $(API) && .venv/bin/ruff check .

format:  ## Auto-fix code style
	cd $(API) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

clean:  ## Remove caches
	python3 scripts/clean.py
