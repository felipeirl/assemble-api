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

Obrigatórias (segredos ficam no `.env`, em *Variables and secrets* do Space e em *Actions secrets* do GitHub):

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

## Deploy no Hugging Face Space

1. Crie um Space com **SDK Docker** e hardware *CPU basic*.
2. Acrescente ao topo deste README, no repositório do Space, o front matter abaixo:

   ```yaml
   ---
   title: Assemble Backend
   sdk: docker
   app_port: 7860
   ---
   ```

3. Cadastre as variáveis obrigatórias em *Settings → Variables and secrets*. Use *Secrets* para chaves e credenciais.
4. Envie o código para o repositório do Space (`git push`). O Space faz o build do `Dockerfile` sozinho.
5. Na primeira subida, o Laya baixa os pesos do Hugging Face Hub, com cerca de 1,3 GB. O download acontece em segundo plano e, até terminar, as chamadas de chat e de match esperam o carregamento.

O Space gratuito dorme após 48 h sem uso. Antes de uma demonstração, chame `GET /health` e espere a resposta. A primeira pode levar alguns minutos.

## Jobs agendados (GitHub Actions)

`.github/workflows/jobs.yml` chama, todo dia:

| Horário (São Paulo) | Rota | Função |
|---|---|---|
| 03:00 | `POST /jobs/ingest` | ingestão incremental da Comic Vine |
| 03:30 | `POST /jobs/purge` | apaga contas após 30 dias, conversas ocultas e logs após 180 dias |
| 05:00 | `POST /jobs/personas` | gera fichas pendentes |

Cadastre em *Settings → Secrets and variables → Actions*:

- `ASSEMBLE_API_URL`: URL do Space, ex.: `https://usuario-assemble.hf.space`
- `JOBS_KEY`: o mesmo valor do Space

Para rodar um job manualmente, use *Actions → Scheduled jobs → Run workflow*. As rotas respondem `202` e o trabalho segue em segundo plano.

## Casamento com a Superhero API

A Superhero API não tem o ID da Comic Vine. O casamento segue esta ordem (`Assemble-perfis-e-fontes.md` §3.1):

1. a tabela manual `data/superhero_matches.json`;
2. a regra automática, que exige nome, nome real e editora aceita iguais, com um único candidato.

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
