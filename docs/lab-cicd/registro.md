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

### Interação 3: container não sobe após o deploy (produção fora do ar)

**Prompt**: após o merge do PR #2 o usuário perguntou "o que deu?"; a IA consultou o run e o log do job `deploy`. Pedido do usuário depois do diagnóstico: "Sim, corrigir".

**Resultado**: `test` e `firestore-rules` verdes; `deploy` falhou de novo. Desta vez o build passou (o `requirements.txt` foi aceito), mas o container não iniciou: `exec: "uvicorn": executable file not found in $PATH`. A produção ficou fora do ar (HTTP 404, página "Site em manutenção"), porque a troca do container já tinha acontecido.

**Problema encontrado**: o `requirements.txt` mínimo (só `uv`) da Interação 2 foi uma aposta da IA, errada: a Discloud ignora o `START` e roda `uvicorn main:app` direto, então o `uvicorn` precisa estar instalado pelo `pip`. A IA também não avisou antes que um commit pela API podia derrubar o app em produção.

**Alterações realizadas**: o job `deploy` passa a gerar o `requirements.txt` completo com `uv export` a partir do `uv.lock`, com a linha `--extra-index-url https://download.pytorch.org/whl/cpu` no topo (o lock pina `torch==2.14.1+cpu`, que só existe nesse índice), e confere que `uvicorn`, `fastapi` e `torch` estão no arquivo. O job usa `setup-uv`.

### Interação 4: run vermelho com o app no ar; verificação real no painel

**Prompt**: após o merge do PR #3 o usuário pediu para verificar. A IA mostrou que o app estava no ar (`/health` 200) mas o run da `main` estava vermelho. O usuário respondeu: "nao adianta subir pr em cima de pr, preciso que valide realmente, caso precise, acessa o discloud pelo meu brave, verifique, e suba uma pr definitiva".

**Resultado do run (`603a110`)**: `test` e `firestore-rules` verdes; `deploy` vermelho em "Enviar o commit à Discloud" (`jq: parse error`) depois de cerca de 2 minutos. A resposta da API de commit não era JSON (página de erro do proxy). O passo morreu antes de checar o código HTTP e o smoke test nem rodou.

**Verificação no painel da Discloud (navegador do usuário)**
- App `assemble` online, 1.79 GB / 2.25 GB; logs mostram o servidor iniciado às 21:54:41 (BRT), "Laya aquecido em 15 s" e `GET /health` 200. O container novo subiu cerca de 40 s depois de o `curl` do job ter desistido (21:54:03): o build seguiu do lado da Discloud.
- O deploy do PR #3 aparece na Atividade como "foi alterado com sucesso" (21:54); os dois anteriores (PR #1 e #2) aparecem com "Ver log do erro", os mesmos erros vistos no GitHub.
- As variáveis de ambiente do painel foram preservadas pelo commit via API (o app subiu com `FIREBASE_SERVICE_ACCOUNT_JSON`, `UVICORN_PORT` etc.); o comando de início do painel é `uvicorn main:app --host 0.0.0.0 --port 8080`.
- **Achado:** em Configurações → Integração com GitHub o **Auto-deploy do app `assemble` continua ativo** (branch `main`). A Atividade registra um "Um novo commit foi feito no repositório" a cada merge (21:34, 21:41, 21:51). Enquanto estiver ligado, a Discloud publica sem esperar a CI e o requisito "CD só se a CI passar" não vale.

**Problemas encontrados**
1. O passo de envio abortava com resposta não JSON do proxy e o job ficava vermelho com o app no ar.
2. O smoke test em `/health` podia dar verde com o container antigo ainda respondendo.
3. Auto-deploy nativo da Discloud ainda ligado.

**Alterações realizadas**: a lógica de deploy foi movida para `.github/scripts/discloud-deploy.sh` (`commit` e `wait-ready`). O `commit` registra o código HTTP, mostra o corpo sem depender de `jq` e só tolera 502/503/504/524 e estouro de tempo do `curl`; o `wait-ready` exige que `startedAt` (de `GET /v2/app/assemble/status`) seja posterior ao envio e que `/health` responda. O script foi testado localmente contra um servidor Discloud simulado em seis cenários (proxy 504, commit 400, app sem reiniciar, status ilegível, `/health` 503, estouro de tempo do `curl`): todos se comportaram como esperado. O comportamento real da API de status só se confirma no primeiro run na `main`.

### Interação 5: o run verde passou por uma página de erro do proxy

**Prompt**: o usuário mandou verificar o merge do PR #4 ("mergeado"), depois de pedir antes que eu desligasse o Auto-deploy ("Sim, desligar"). Ao achar o furo abaixo, a IA o relatou e o usuário respondeu: "Sim, ajustar".

**Ação feita pela IA com autorização do usuário**: no painel da Discloud (navegador do usuário), desliguei só o interruptor **Auto-deploy do app `assemble`** (Configurações → Integração com GitHub); confirmei depois de recarregar ("Inativo"). Os apps `quimia-*` não foram tocados.

**Resultado do run (`bcc6717`)**: os três jobs verdes. A Atividade da Discloud mostra uma única entrada às 22:07, "foi alterado com sucesso", sem o evento "novo commit" do GitHub: o Auto-deploy desligado surtiu efeito e só o pipeline publicou. A API respondeu HTTP 200 ao commit em 15 s.

**Problema encontrado**: o `wait-ready` passou na 1ª tentativa às 22:07:48 (BRT) e o log do app mostra o servidor iniciando às 22:07:49. O corpo recebido pelo job era a página HTML "Erro interno" do proxy, com HTTP 200, e o `curl --fail` a aceitou como saúde. O verde veio de uma página de erro, 1 s antes de o app subir; com o container quebrado, o pipeline poderia ter dado verde. O teste simulado do PR #4 não cobria esse caso.

**Alterações realizadas**: `wait-ready` passa a usar `/ready` e só aceita HTTP 200 com JSON cujo campo `laya` seja `warm` ou `off` (o app devolve 503 enquanto o Laya carrega). O teste simulado ganhou dois cenários: HTML de erro com HTTP 200 (G) e JSON 200 com `laya: loading` (H). Rodei os oito cenários no script novo (todos como esperado) e G e H no script antigo, para provar a regressão: o antigo dava verde nos dois, o novo falha.

<!-- Próximas interações: registrar aqui, uma por uma, conforme acontecerem. -->

(O texto do Prompt 1 acima mantém a URL `.app`, como foi de fato enviado.)

## Respostas finais (preencher ao concluir)

1. Quantos prompts até a versão final:
2. Principais problemas encontrados:
3. Alterações necessárias:
4. Alterações feitas manualmente:
5. Como verifiquei que a pipeline funciona:
