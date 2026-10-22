.PHONY: dev test build verify quality

PYTHON ?= python3

dev:
	$(PYTHON) scripts/dev.py

test:
	$(PYTHON) -m pytest -q

build:
	npm --prefix frontend run build

verify: test build

quality:
	$(PYTHON) scripts/verify_m4_quality.py
