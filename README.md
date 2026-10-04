# Assemble — Backend

Único servidor do app Assemble (Android). Verifica o login do Firebase, grava no Firestore, monta o baralho diário, decide o match e conversa com o usuário como uma versão **ficcional** do personagem, gerada por IA.

- Especificação: `Assemble-backend-python.md`
- Contrato da API V2: `Assemble-contrato-api.md` (prevalece em rotas, formatos e erros)
- Perfis personalizáveis e fontes de dados: `Assemble-perfis-e-fontes.md`

## Arquitetura

```
app/
  main.py            FastAPI, rotas e aquecimento do Laya
  config.py          variáveis de ambiente (pydantic-settings)
  container.py       montagem das dependências (Firestore, IA, serviços)
  auth.py            token do Firebase, conta desativada, X-Jobs-Key
  access_log.py      accessLogs (Marco Civil, 180 dias)
  api/               rotas /v2/* e /jobs/*, objetos do contrato
  domain/            compatibilidade, baralho e decisão de match (funções puras)
  services/          baralho, decisões, conversa, perfil, conta
  catalog/           ingestão Comic Vine + Marvel Database (Fandom) + Superhero API
  ai/                LiteLLM (Command Code), guardrail Laya, fichas de persona, chat
  store/             acesso a documentos (Firestore e memória, para testes)
data/                tabelas versionadas: poderes, equipes, origens, lista do tier A
firestore.rules      regras de segurança do Firestore (só o app; o backend usa o Admin SDK)
.github/workflows/   jobs agendados (ingestão, fichas, purge)
```

## Rodar localmente

Requisitos: Python 3.12 e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

Preencha o `.env`, que é ignorado pelo git. Sem `FIREBASE_SERVICE_ACCOUNT_JSON` o servidor não sobe. Sem as chaves da Comic Vine ou do Command Code, as rotas que dependem delas respondem `503 provider_unavailable`.

Verificação: `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`.

Com Docker:

```bash
docker build -t assemble-backend .
docker run --env-file .env -p 7860:7860 assemble-backend
```

## Testes e lint

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Os testes usam Firestore em memória e falsos para Firebase Auth, LLM e Laya. Nenhuma chamada externa é feita.

## Variáveis de ambiente

Obrigatórias (segredos ficam no `.env`, no Secret Manager do Google Cloud e em *Actions secrets* do GitHub):

| Variável | Uso |
|---|---|
| `FIREBASE_SERVICE_ACCOUNT_JSON` | credencial do Admin SDK (conteúdo JSON) |
| `COMICVINE_API_KEY` | API da Comic Vine |
| `COMMANDCODE_API_KEY` | Provider API do Command Code |
| `COMMANDCODE_BASE_URL` | `https://api.commandcode.ai/provider/v1` |
| `CHAT_MODEL` / `CHAT_FALLBACK_MODEL` | modelo de chat e reserva (ids em `GET /provider/v1/models`) |
| `PERSONA_MODEL` | modelo das fichas de persona (só dados públicos de personagens) |
| `JOBS_KEY` | segredo das rotas `/jobs/*` |
| `DEFAULT_TIMEZONE` | padrão `America/Sao_Paulo` |

Opcionais (valores padrão em `app/config.py`):

| Variável | Padrão | Uso |
|---|---|---|
| `MATCH_WEIGHT_COMPATIBILITY` / `_AFFINITY` / `_CHANCE` | 0.6 / 0.3 / 0.1 | pesos p1, p2, p3 do match |
| `MATCH_CUTOFF` | 0.55 | corte do match |
| `DECK_SIZE` | 30 | personagens por dia |
| `MESSAGES_PER_HOUR` | 60 | limite de mensagens por usuário |
| `CHAT_HISTORY_LIMIT` | 20 | mensagens enviadas ao modelo |
| `GUARDRAIL_ENABLED` / `GUARDRAIL_THRESHOLD` | true / 0.5 | Laya e limiar de bloqueio |
| `TIER_B_MIN_APPEARANCES` | 50 | aparições mínimas do tier B |
| `INGEST_MAX_REQUESTS_PER_RESOURCE` | 190 | requisições à Comic Vine por recurso, por execução |
| `INGEST_REQUEST_INTERVAL_SECONDS` | 1.0 | espaçamento entre requisições |
| `PERSONA_BATCH_SIZE` | 20 | fichas por execução do job |

Toda chamada de chat envia `x-cmd-zdr: 1` (retenção zero). As fichas de persona não usam ZDR, porque o modelo pode treinar com elas. Por isso recebem só dados públicos dos personagens, nunca mensagens de usuários.

## Firestore

- Crie o banco na região **EUA**. A região é permanente.
- Publique as regras com a [Firebase CLI](https://firebase.google.com/docs/cli): `firebase deploy --only firestore:rules`.
- O backend não depende de índices compostos.

Testes das regras no emulador. Exigem Node 20+ e Java 21+:

```bash
cd firestore-tests
npm install
npm test
```

## Execução e deploy

**Hoje o backend roda no PC e o celular acessa por um túnel ngrok**: `docs/local-run.md` tem o passo a passo (configuração do `.env`, subir o servidor, abrir o túnel e fazer a carga do catálogo).

O deploy no Google Cloud Run continua preparado e é opcional: `docs/cloud-run.md` descreve a configuração, e o workflow `Test and deploy` só publica quando é executado manualmente. A cada push na `main` ele roda os testes Python e os testes das regras do Firestore.

## Jobs

| Rota | Função |
|---|---|
| `POST /jobs/ingest` | ingestão incremental da Comic Vine |
| `POST /jobs/personas` | gera fichas de persona pendentes (ordem: ingest, depois personas) |
| `POST /jobs/translations` | traduz para pt-BR os textos longos do perfil (`bio`, `occupation`, `base`, `placeOfBirth`, `relatives`) com o `PERSONA_MODEL`; rode depois do ingest |
| `POST /jobs/purge` | apaga contas após 30 dias, conversas ocultas e logs após 180 dias |

Todas exigem o header `X-Jobs-Key` e respondem `202`: o trabalho segue em segundo plano. Os jobs **não têm agenda**, porque o backend roda no PC. Execute-os de duas formas:

- direto no PC, com `Invoke-RestMethod` (`docs/local-run.md`, seção 3);
- pelo workflow `Jobs` (*Actions → Jobs → Run workflow*), que exige os secrets `ASSEMBLE_API_URL` (o domínio do ngrok) e `JOBS_KEY`, e o PC ligado com o túnel aberto.

Com o backend sempre no ar (Cloud Run), acrescente um `schedule` ao `jobs.yml`.

## Guardrail (Laya)

O Laya multilíngue roda na CPU e faz perguntas sim/não sobre cada mensagem. Os limiares foram **calibrados com frases reais** (37 inocentes, 0 bloqueadas; 10 maliciosas, todas bloqueadas), porque um limiar único não serve: o modelo dá 1,00 de "jailbreak" até para "Você já errou feio?".

- **Autoagressão:** palavras-chave em pt e en, mais o modelo (limiar 0,35). Responde com o encaminhamento ao CVV 188.
- **E-mail, telefone e CPF:** regras determinísticas; o Laya sozinho não os detecta de forma confiável.
- **Jailbreak, sexual e romance:** o sinal do modelo só vale com um indício textual junto; padrões inequívocos ("ignore as instruções anteriores") bloqueiam sozinhos.
- **Saída do modelo e bio da fonte:** limiares próprios (`app/ai/guardrail.py`).
- **Chat só com modelos de retenção zero.** Modelos `contributor` treinam com o que recebem e são recusados na configuração; ficam restritos às fichas e traduções (dados públicos).

Ao trocar o modelo do Laya ou as perguntas, meça de novo antes de mexer nos limiares.

## Idioma (pt-BR)

- **Nomes:** tabela curada `data/names_ptbr.json` (`characterId` → nome em português). Sem entrada, vale o nome original; nunca se inventa tradução. Para acrescentar, edite o arquivo e suba o campo `version`.
- **Textos longos:** traduzidos por IA uma vez (`/jobs/translations`) e guardados em `translations.pt-BR` no personagem. A tradução se refaz sozinha quando o texto de origem muda.
- **No original, por decisão:** apelidos (`aliases`) e primeira aparição.
- A API escolhe o idioma pelo `Accept-Language`.

## Casamento com a Superhero API

A Superhero API não tem o ID da Comic Vine. O casamento segue esta ordem (`Assemble-perfis-e-fontes.md` §3.1):

1. a tabela manual `data/superhero_matches.json`;
2. a ponte Wikidata: o item com o ID da Comic Vine ([P5905](https://www.wikidata.org/wiki/Property:P5905)) traz o rótulo e os apelidos, e o candidato só é aceito se for único com nome real entre esses nomes;
3. a regra automática, que exige nome, nome real e editora aceita iguais, com um único candidato.

O que não casar fica sem enriquecimento e entra na fila de revisão. Para exportar a fila:

```bash
uv run python -m app.catalog.export_review
```

O comando gera `data/superhero_review.json`. Confirme o id na fonte, copie o par para `superhero_matches.json` e suba a versão do arquivo. Isso força a reingestão dos personagens.

## Fontes e licenças

- Fatos dos personagens: [Comic Vine](https://comicvine.gamespot.com/api/).
- Seção "Personality": [Marvel Database](https://marvel.fandom.com/) (CC BY-SA). A URL de origem fica guardada em `sources` para o crédito.
- Afiliações complementares e, em breve, atributos, aparência e dados de perfil: [Superhero API](https://akabab.github.io/superhero-api/) (MIT).
- Planejadas: [Wikidata](https://www.wikidata.org/) (CC0) como ponte de IDs e o conjunto `comic-characters` da [FiveThirtyEight](https://github.com/fivethirtyeight/data) como reserva. Detalhes em `Assemble-perfis-e-fontes.md`.
- Toda fala de personagem é **ficção gerada por IA**, nunca canon nem aprovada pela editora.
