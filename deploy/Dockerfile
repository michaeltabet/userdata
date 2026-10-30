# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
#
# USERDATA server image: the MCP server over streamable HTTP, plus Arelle's
# command line for taxonomy validation and the iXBRL viewer.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 10001 userdata
USER userdata
ENV USERDATA_CONFIG=/app/userdata.toml PATH=/app/.venv/bin:$PATH
VOLUME ["/data"]
EXPOSE 8765

CMD ["userdata", "serve", "--http"]
