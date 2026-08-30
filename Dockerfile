FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY data/fixtures ./data/fixtures
COPY knowledge_base/policy ./knowledge_base/policy
COPY evals/golden ./evals/golden

RUN useradd --create-home --uid 10001 copilot && mkdir -p /app/artifacts && chown -R copilot:copilot /app
USER copilot
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
