FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

# Copy dependency metadata first to maximize layer caching.
COPY pyproject.toml /app/

# Create a local virtual environment from project dependencies using uv.
RUN uv sync --no-dev --no-install-project

FROM python:3.12-slim AS runtime

WORKDIR /app

# Reuse the virtual environment produced in the builder stage.
COPY --from=builder /app/.venv /app/.venv
COPY main.py /app/main.py

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["python", "main.py"]
