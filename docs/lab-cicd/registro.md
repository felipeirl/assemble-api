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

**Problema encontrado**: nenhum no PR #1 (CI verde; `deploy` pulado, como esperado em `pull_request`). Os problemas apareceram só na execução na `main` (Interação 2).

**Alteração realizada**: `deploy.yml` (Cloud Run manual) movido para `_archive/deploy-cloud-run.yml`; `docs/discloud.md` passo 2 reescrito.

### Interação 2: falha do deploy na `main`

**Prompt**: após o merge do PR #1, o usuário avisou que o merge estava feito; a IA consultou a execução (`gh run view`) e o log do job `deploy`. Pedido do usuário depois do diagnóstico: "Sim, corrigir".

**Resultado**: CI verde (`test`, `firestore-rules`); `deploy` falhou com HTTP 400. Token e `appID` foram aceitos e a Discloud iniciou o build, mas o builder dela faz `COPY app/requirements.txt` e o repositório nunca teve esse arquivo. A API seguiu no ar na versão anterior.

**Problemas encontrados**
1. Falta de `requirements.txt` no zip (a `docs/discloud.md` já avisava; o job não tratava).
2. URL pública errada: o padrão no workflow e nos docs era `https://assemble.discloud.app`, que não resolve; a correta é `https://assemble.discloud.dev` (conferido com `curl`: `{"status":"ok"}`). O smoke test teria falhado por isso.

**Alterações realizadas**: o job `deploy` gera `requirements.txt` (conteúdo `uv`; o `BUILD` do `discloud.config` já sincroniza tudo pelo `uv.lock`) e o inclui no zip, com checagem de presença; padrão de `APP_URL` e `docs/discloud.md` corrigidos para `.dev`.

**Alterações manuais do usuário**: criar o secret `DISCLOUD_API_TOKEN`, desligar o deploy automático nativo da Discloud e fazer o merge do PR #1.

<!-- Próximas interações: registrar aqui, uma por uma, conforme acontecerem. -->

(O texto do Prompt 1 acima mantém a URL `.app`, como foi de fato enviado.)

## Respostas finais (preencher ao concluir)

1. Quantos prompts até a versão final:
2. Principais problemas encontrados:
3. Alterações necessárias:
4. Alterações feitas manualmente:
5. Como verifiquei que a pipeline funciona:
