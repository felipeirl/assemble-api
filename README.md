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
| `DECK_SIZE` | 40 | personagens por dia |
| `MESSAGES_PER_HOUR` | 60 | limite de mensagens por usuário |
| `CHAT_HISTORY_LIMIT` | 40 | mensagens enviadas ao modelo (cerca de 20 trocas) |
| `MEMORY_MODEL` | `deepseek/deepseek-v4.1-flash` | modelo que escreve o resumo da conversa (retenção zero, sem raciocínio) |
| `MEMORY_BATCH_SIZE` | 10 | mensagens fora da janela que acumulam antes de entrarem no resumo |
| `MEMORY_CHUNK_SIZE` | 30 | mensagens por chamada ao resumir uma conversa antiga |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | vazio | foto do perfil no Cloudinary; sem as três, o app guarda a foto no Firestore |
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

- **Autoagressão:** palavras-chave em pt e en, mais duas perguntas ao modelo sobre a PRÓPRIA pessoa (limiar 0,5 em cada). Responde com o encaminhamento ao CVV 188. Falar de violência, estupro ou da morte de outra pessoa não aciona: a pergunta genérica antiga dava 0,73 para "ela se matou depois de ser estuprada". Medido com o Laya real: 12 de 12 frases de risco pegas e 0 de 12 frases sobre violência ou luto encaminhadas.
- **E-mail, telefone e CPF:** regras determinísticas; o Laya sozinho não os detecta de forma confiável.
- **Jailbreak e sexual:** o sinal do modelo só vale com um indício textual junto; padrões inequívocos ("ignore as instruções anteriores") bloqueiam sozinhos.
- **Romance não é bloqueado.** Elogios e "te amo" chegam ao personagem. Uma nota interna (`MOVE_AFFECTION`, em `app/ai/prompts.py`) pede um agradecimento carinhoso dizendo que ainda não pode dizer o mesmo porque se conhecem há pouco tempo, sem flertar nem se mostrar ofendido. O que continua barrado é o conteúdo sexual (entrada e saída). Fichas antigas com "não fala de romance" são reescritas na hora do prompt.
- **Saída do modelo:** "saiu do personagem" (modelo de linguagem, ChatGPT, roleplay, prompt de sistema...) é pego por palavras-chave. O limiar do modelo para esse motivo é 0,9, porque personagens robôs em personagem pontuam de 0,50 a 0,72, na mesma faixa dos vazamentos reais.
- **Bio da fonte:** limiar próprio (`app/ai/guardrail.py`).
- **Chat só com modelos de retenção zero.** Modelos `contributor` treinam com o que recebem e são recusados na configuração; ficam restritos às fichas e traduções (dados públicos).

Ao trocar o modelo do Laya ou as perguntas, meça de novo antes de mexer nos limiares.

## Tom do chat

O chat deve parecer uma conversa de mensagens, não uma caricatura do personagem. O prompt global (`app/ai/prompts.py`, `persona-v2`) pede respostas de 1 a 2 frases, reação ao que o usuário acabou de dizer, sem bordões nem monólogos. As fichas de persona (`persona-sheet-v2`) descrevem o jeito de escrever em chat, e o job `/jobs/personas` refaz sozinho as fichas de versões anteriores do prompt.

**Tamanho das respostas:** o prompt pede 1 ou 2 frases e no máximo uns 30 palavras, e a nota interna de cada turno fixa um teto de palavras que acompanha o tamanho da mensagem do usuário (de 12 a 35, em `reply_word_limit`). Medido com o modelo real em 10 mensagens: média de 16 palavras e máximo de 26.

**Pedidos de estilo não são jailbreak:** "responda como uma pessoa, com mensagens menores" ou "fala menos" davam 1,00 de jailbreak no Laya e casavam com "responda como". Mensagem com palavra de tamanho ou estilo (menor, curto, mensagens, WhatsApp...) e sem palavra de sobrescrita (instruções, regras, ignore, prompt...) ignora o sinal de jailbreak. O sinal de autoagressão do modelo também só vale com uma palavra-indício ("fala menos, por favor" dava 0,63).

O modelo de chat às vezes devolve só um número ou a lista de sugestões no lugar da resposta. O backend tenta até 3 vezes e nunca mostra JSON cru ao usuário.

## Compatibilidade

Função pura em `app/domain/compatibility.py`, idêntica ao `CompatibilityCalculator` do Android. Pesos: origem 25, poderes 30, equipes 15, estilo 20, fama 10.

- **"Qualquer" é neutro:** a categoria vale metade do peso. Quem deixa tudo em "Qualquer" fica perto de 55, e não casa com todo mundo.
- **Rivalidades:** sem nada em comum na categoria e com um traço rival do escolhido, a categoria perde metade do peso (nota final entre 0 e 100). Um traço em comum anula a rivalidade.
- **Pares (simétricos):** Avengers x X-Men ("Avengers vs. X-Men", 2012), Avengers x Defenders ("The Avengers/Defenders War", 1973), X-Men x S.H.I.E.L.D. (Uncanny X-Men, 2013), Mutante x Humano (preconceito anti-mutante), Mutante x Robô (Sentinelas), Liderança x Solitário, Liderança x Rebelde, Idealista x Sombrio. Poderes não têm rivalidade.

Ao mudar a tabela, mude também no Android.

## Velocidade do chat (raciocínio dos modelos)

Modelos que raciocinam gastam de 1.000 a 2.500 tokens "pensando" antes de uma resposta de uma frase: 10 a 30 s por mensagem. O chat usa modelos escolhidos por medida (`CHAT_MODEL` e `CHAT_FALLBACK_MODEL` no `.env`) e o esforço de raciocínio de cada um vem de `CHAT_REASONING_EFFORTS` (`app/config.py`):

| Modelo | Esforço | Resposta (mediana) |
|---|---|---|
| `google/gemini-3.8-flash` (principal) | `low` (não aceita `off`) | 3,6 s |
| `deepseek/deepseek-v4.1-flash` (reserva) | `off` | 4,4 s |
| `qwen/qwen3.7-flash` (antes) | não desliga | 11,9 s |

O provedor rejeita com 400 um esforço que o modelo não aceita; por isso o valor é por modelo, e modelo fora da tabela vai sem o parâmetro. Chat exige retenção zero (`x-cmd-zdr`): modelos sem ela são recusados pelo provedor. Ao trocar de modelo, meça de novo (latência, tokens de raciocínio e respostas truncadas) antes de adotar.

## Memória da conversa

O personagem lê as últimas `CHAT_HISTORY_LIMIT` (40) mensagens. O que sai dessa janela vira um **resumo rolante**, guardado em `matches/{id}.memory` (`text`, `folded`, `updatedAt`) e enviado no prompt como "o que você lembra desta conversa".

- **Quando atualiza:** depois de cada resposta, em segundo plano (`BackgroundTasks`), então o usuário nunca espera. Uma estimativa barata (`userMessageCount`) evita ler a conversa quando não há o que resumir. Quando `MEMORY_BATCH_SIZE` mensagens já saíram da janela, elas são dobradas no resumo anterior, em blocos de `MEMORY_CHUNK_SIZE`. `folded` conta quantas mensagens já entraram.
- **O que o modelo escreve** (`app/ai/memory.py`): até 120 palavras, em pt-BR, com o que o usuário contou, combinados e assuntos em aberto, mais o que o personagem disse de si que importa depois. As mensagens entram como dado: instruções dentro delas são ignoradas.
- **Falhas:** se o modelo ou o guardrail falhar, o resumo anterior é mantido e a próxima resposta tenta de novo. O chat nunca é afetado.
- **Segurança:** o resumo passa pelos guardrails de saída e de injeção antes de ser guardado, tem no máximo 900 caracteres e só usa modelo de retenção zero.
- **Voltar a conversa:** se o destino for anterior ao que o resumo cobre, o resumo é apagado e refeito aos poucos. **Ocultar conversas** apaga o resumo junto.
- **O app não mostra nem edita o resumo**, e as regras do Firestore não deixam o app escrevê-lo.
- **Medido com o modelo real:** conversa de 100 mensagens com 6 fatos do usuário contados no começo (nome do cachorro, profissão, medo, irmã, comida, cidade de origem). Sem resumo o personagem acertou 0 de 6 perguntas; com resumo, 6 de 6. Resumir 60 mensagens levou cerca de 42 s, em segundo plano.

## Foto do perfil (Cloudinary)

Com `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` e `CLOUDINARY_API_SECRET` no `.env`, a foto do perfil vai para o Cloudinary em vez de ficar em Base64 no documento do usuário.

- `POST /v2/me/photo/signature` devolve `{uploadUrl, fields}`: a URL de envio e os campos do formulário já **assinados** (`app/media.py`). O app envia o JPEG direto ao Cloudinary; o segredo da API nunca sai do servidor.
- A assinatura fixa `public_id` (o uid do usuário), a pasta `assemble/avatars`, `overwrite` e a transformação (recorte quadrado de 256 px em JPEG, centrado no rosto). O app não consegue enviar outra coisa nem trocar a foto de outra pessoa.
- O app grava a URL `https://res.cloudinary.com/...` em `users/{uid}.avatarPhoto`; as regras do Firestore só aceitam essa origem (ou o Base64 de antes).
- Sem as variáveis, a rota responde `503 provider_unavailable` e o app salva a foto em Base64, como antes. Falha de rede no envio tem o mesmo efeito: salvar o perfil nunca falha por causa da foto.
- Na exclusão definitiva da conta (job `purge`), a foto é apagada do Cloudinary; se o Cloudinary falhar, a exclusão segue.

## Regenerar e voltar a conversa

- `POST /v2/connections/{id}/messages/regenerate`: gera outra resposta no lugar da última do personagem. A mensagem mantém o `id`, então quem escuta o Firestore vê o texto mudar no lugar. Responde `409 nothing_to_regenerate` se a última mensagem não é do personagem ou se a anterior foi recusada. Conta no limite de mensagens por hora, mas não em `userMessageCount`. Se só existe a fala de abertura, gera outra abertura.
- `POST /v2/connections/{id}/messages/rewind` com `{"messageId": "..."}`: apaga tudo o que veio depois de uma resposta do personagem (a abertura vale) e responde `204`. Refaz `lastMessagePreview`, `userMessageCount` e as sugestões. Mensagem de usuário como alvo dá `400`, e id desconhecido dá `404`.
- Editar a mensagem do usuário ficou para depois: deixaria a resposta seguinte órfã.

## Baralho

- **Cota do dia:** `DECK_SIZE` (40) decisões por dia, contadas por `deckDate` nas decisões. Quem recebeu Pass ou Assemble não volta; Undo desfaz só o último Pass.
- **Sorteio a cada abertura:** `GET /v2/deck` sorteia de novo entre os personagens que o usuário ainda não decidiu. Fechar e abrir o app gira os personagens, e o baralho de cada pessoa sai diferente. O documento `decks/{data}` guarda só o necessário para o Undo, não a lista de cards.
- **Como sorteia** (`app/domain/deck.py`): nota de compatibilidade (peso `SCORE_WEIGHT` = 3), bônus de novidade, penalidade de variedade proporcional (a fração do baralho já ocupada pela mesma origem e equipes) e sorte `JITTER` de 0 a 0,6. Com esse peso, entram cerca de 20 dos 25 personagens mais compatíveis (com peso 1 eram 15) e a nota média do baralho sobe de 74 para 78 (o conjunto todo tem 72). Para favorecer mais ou menos, mude `SCORE_WEIGHT`: 4 dá 22 dos 25 melhores e baralhos mais parecidos entre aberturas. Medido com duas contas reais: 18 de 40 personagens em comum entre pessoas e 23 de 40 entre duas aberturas da mesma conta, antes eram 28 e 35.
- A penalidade de variedade antiga somava 0,1 por repetição e passava de 2,0 no meio da seleção; por isso os personagens de origem rara entravam sempre e o baralho era quase igual para todos.

### Metade compatíveis, metade sugestões

O baralho de 40 cards tem duas metades, sem marca no card:

- **20 compatíveis:** os de maior nota com as preferências declaradas, como descrito acima.
- **20 sugestões:** o que sobrou, escolhido pelo **gosto aprendido** (`app/domain/taste.py`). Cada Assemble conta a favor das características do personagem (origem, equipe, poderes, estilo, faixa de fama e, quando a Superhero API tem o dado, herói/vilão e gênero) e cada Pass contra. O gosto é recalculado das decisões a cada baralho, sem guardar nada: o Undo já se reflete sozinho, e as preferências declaradas nunca são alteradas.
- **Começo:** sem decisões, as sugestões exploram (variedade e sorte). A confiança no gosto aprendido cresce até 100% em 20 decisões (`CONFIDENT_AFTER_DECISIONS`); antes disso, é proporcional.
- **Medido com um usuário sintético** (gosta de mutantes e X-Men; catálogo real; chance de curtir sem critério: 0,42): as sugestões agradam 0,37 sem decisões, 0,56 com 10, 0,66 com 20 e 0,68 com 40. Sem esticar o gosto entre os candidatos, eram só 0,47 com 40.
- A chance de match continua usando só a compatibilidade declarada.

### Rodada de reação do cadastro

O cadastro mostra 12 personagens para a pessoa tocar em Curti ou Pular, só para o app conhecer o gosto dela.

- `GET /v2/onboarding/reaction-cards`: 12 cards (`app/domain/reaction.py`) entre os 36 mais conhecidos, escolhidos para cobrir o máximo de origens, equipes, estilos e alinhamentos diferentes.
- `PUT /v2/taste-signals/{characterId}` com `{"liked": true}`: grava o sinal em `users/{uid}/tasteSignals/{characterId}` e responde `204`.
- **Não é decisão:** o personagem continua no baralho, pode virar conexão e não conta na cota do dia. O sinal entra no gosto aprendido como uma decisão; se a pessoa decidir sobre o mesmo personagem depois, vale a decisão.
- Alinhamento e gênero existem só em 68 dos 106 personagens; nos outros, simplesmente não geram característica.

### Frase "o que você procura"

O app grava `lookingFor` (até 140 caracteres) no documento do usuário. Como a bio, é dado não confiável: só é usado se o guardrail aprovar. Entra no perfil enviado ao Laya para a afinidade e na instrução da fala de abertura (inclusive ao regenerar a abertura), como dica para a primeira pergunta.

## Card do baralho

Cada card traz `tagline`: a primeira frase da bio (em pt-BR, da tradução, quando existe), com até 140 caracteres e sem o título de seção do Comic Vine. Sem bio, o campo não vem.

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
