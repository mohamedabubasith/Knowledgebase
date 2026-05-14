FROM python:3.12-slim

WORKDIR /app

# System deps for PyMuPDF, python-magic, libmagic
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install dependencies from lockfile (reproducible)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Pre-download ST model at build time (avoids cold start in prod)
ARG ST_MODEL=all-MiniLM-L6-v2
RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${ST_MODEL}')"

COPY app/ app/

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--loop", "uvloop"]
