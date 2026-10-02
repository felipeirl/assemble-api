FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/home/appuser/.cache/huggingface \
    PATH="/home/appuser/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv

# Usuário sem privilégios; instalar já como ele evita um chown sobre o torch.
RUN useradd --create-home --uid 1000 appuser
USER appuser
WORKDIR /home/appuser/app

COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

# Os pesos do Laya (cerca de 650 MB) entram na imagem: sem isso, cada partida a frio no
# Cloud Run baixaria tudo de novo antes de o guardrail responder.
RUN python -c "from app.ai.guardrail import build_laya_router; build_laya_router().preload(['multilingual'])"

# O Cloud Run informa a porta em $PORT; 7860 vale para execução local.
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
