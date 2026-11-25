FROM python:3.13-slim

COPY --from=astral/uv:0.13.7 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, for layer caching
COPY pyproject.toml uv.lock .python-version README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project

COPY src/ src/
COPY pg_replication/ pg_replication/
COPY data/ data/
COPY .dlt/config.toml .dlt/config.toml
RUN uv sync --locked --no-dev

# Entry points run without `uv run`, which would install the dev group at start
ENV PATH="/app/.venv/bin:$PATH"

CMD ["fc-pipeline"]
