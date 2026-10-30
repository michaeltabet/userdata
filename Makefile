.PHONY: setup test lint licenses

setup:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uvx --with-editable . pylint --rcfile=pylintrc src tests
	uvx pyrefly check --python-interpreter-path .venv/bin/python
	uvx sqlfluff lint migrations

licenses:
	uv run pip-licenses --from=mixed --ignore-packages userdata --fail-on="GPL;AGPL;SSPL;BUSL"
