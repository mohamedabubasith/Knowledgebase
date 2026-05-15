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
    # No PYTHONDONTWRITEBYTECODE — would discard .pyc files uv compiled at build time
    # and force recompilation on every cold start (~6s overhead).
    PATH="/app/.venv/bin:$PATH"

# Install dependencies from lockfile (reproducible)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Pre-download ST model at build time (avoids cold start in prod)
ARG ST_MODEL=all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${ST_MODEL}')"

COPY app/ app/

EXPOSE 8080

# Call venv uvicorn directly — skip uv run overhead (bytecode recompile + env resolve on every start)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--loop", "uvloop"]
