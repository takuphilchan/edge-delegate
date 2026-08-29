PYTHON ?= python

.PHONY: install-dev lint test test-hardware demo verify

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	ruff check .

test:
	$(PYTHON) -m pytest

test-hardware:
	$(PYTHON) -m pytest -m hardware

demo:
	$(PYTHON) -m edge_delegate demo

verify: lint test

