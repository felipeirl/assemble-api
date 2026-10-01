# Assemble — Backend

Servidor FastAPI do app Assemble. Especificação: `Assemble-backend-python.md`; contrato da API: `Assemble-contrato-api.md` (prevalece em rotas, formatos e erros).

## Rodar localmente

```bash
uv sync
cp .env.example .env   # preencha os valores; o .env é ignorado pelo git
uv run uvicorn app.main:app --reload
```

Verificação: `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`.

## Testes e lint

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `FIREBASE_SERVICE_ACCOUNT_JSON` | credencial do Admin SDK (conteúdo JSON) |
| `COMICVINE_API_KEY` | API da Comic Vine |
| `COMMANDCODE_API_KEY` | Provider API do Command Code |
| `COMMANDCODE_BASE_URL` | URL base do provedor (confirmar) |
| `CHAT_MODEL` / `CHAT_FALLBACK_MODEL` | modelo de chat e reserva |
| `PERSONA_MODEL` | modelo para gerar fichas de persona |
| `JOBS_KEY` | segredo das rotas `/jobs/*` |
| `DEFAULT_TIMEZONE` | padrão `America/Sao_Paulo` |

Nenhum segredo vai para o repositório. Deploy no Hugging Face Space e configuração dos jobs agendados serão documentados na etapa 12.
