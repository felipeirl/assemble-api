# Registro do LAB CI/CD com IA generativa

Projeto: `felipeirl/assemble-api` (FastAPI, Python 3.12, uv). Destino do deploy: Discloud.
IA usada: Claude Code. Este arquivo é a fonte do PDF de entrega.

## Estado inicial (verificado antes do Prompt 1)

- `.github/workflows/deploy.yml` já rodava CI em push/PR, mas o deploy (Google Cloud Run) era só manual (`workflow_dispatch`).
- A Discloud tinha deploy automático nativo a cada push na `main`, sem depender da CI.

## Interações

### Prompt 1: criação da pipeline

**Prompt**

```text
Contexto: tenho um projeto em Python 3.12 (FastAPI, gerenciado com uv) no GitHub
(felipeirl/assemble-api), hoje publicado na Discloud como site em
https://assemble.discloud.app. Tarefa de faculdade: criar uma pipeline CI/CD com
GitHub Actions.

Requisitos:
1. CI em push e pull_request na branch main: checkout, setup do uv, `uv sync --frozen`,
   `ruff check`, `ruff format --check`, `pytest`, e o job de regras do Firestore
   (Node 22 + Java 21, em firestore-tests/).
2. CD só em push na main e só se TODOS os jobs de CI passarem (needs + if).
3. Deploy na Discloud via API: PUT https://api.discloud.app/v2/app/{appID}/commit,
   header api-token, multipart com campo `file` (.zip contendo discloud.config e
   excluindo o que está no .discloudignore). Token no secret DISCLOUD_API_TOKEN.
4. Smoke test pós-deploy: GET /health com retentativas (o app leva a aquecer um modelo).
5. Sem credenciais no YAML, permissões mínimas, concurrency sem cancelar deploy em curso.

Anexos: .github/workflows/deploy.yml atual, discloud.config, .discloudignore,
pyproject.toml. Entregue o YAML completo e explique cada decisão não óbvia.
```

**Resultado**: `.github/workflows/ci-cd.yml` com os jobs `test`, `firestore-rules` e `deploy`. O zip é montado com `git archive` e exclusões, enviado por `curl` à API de commit, seguido de smoke test em `/health`.

**Problema encontrado**: ainda não executado no GitHub.

**Alteração realizada**: `deploy.yml` (Cloud Run manual) movido para `_archive/deploy-cloud-run.yml`; `docs/discloud.md` passo 2 reescrito.

<!-- Próximas interações: registrar aqui, uma por uma, conforme acontecerem. -->

## Respostas finais (preencher ao concluir)

1. Quantos prompts até a versão final:
2. Principais problemas encontrados:
3. Alterações necessárias:
4. Alterações feitas manualmente:
5. Como verifiquei que a pipeline funciona:
