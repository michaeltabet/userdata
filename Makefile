.PHONY: setup migrate test licenses lint schema-doc
UV ?= uv
ALLOWED = MIT License;Apache Software License;BSD License;ISC License (ISCL);Python Software Foundation License;Apache-2.0;MIT;BSD-3-Clause;BSD-2-Clause;ISC;PSF-2.0;Public Domain;The Unlicense (Unlicense);Mozilla Public License 2.0 (MPL 2.0);Apache-2.0 OR BSD-2-Clause;Apache-2.0 OR BSD-3-Clause;MIT-0

setup:
	$(UV) sync

migrate:
	$(UV) run userdata migrate

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check src tests scripts
	$(UV) run ruff format --check src tests scripts

licenses:
	$(UV) run pip-licenses --from=mixed --allow-only="$(ALLOWED)" --ignore-packages userdata

schema-doc:
	$(UV) run python scripts/schema_doc.py
