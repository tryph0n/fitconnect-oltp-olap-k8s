FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.14 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version README.md ./

# Install dependencies only (not the project itself yet)
RUN uv sync --no-dev --no-install-project

# Copy source code and data
COPY src/ src/
COPY data/ data/

# Now install the project (editable)
RUN uv sync --no-dev

CMD ["uv", "run", "fc-pipeline"]
