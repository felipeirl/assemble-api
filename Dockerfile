FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv

# O Space roda como usuário 1000; instalar já como ele evita um chown sobre o torch.
RUN useradd --create-home --uid 1000 appuser
USER appuser
WORKDIR /home/appuser/app

COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

ENV PATH="/home/appuser/app/.venv/bin:$PATH"
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
