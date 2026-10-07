# Assemble — Contrato da API V2

Contrato entre o app Android e o backend Python. Em rotas, formatos e erros, este documento vale.

## 1. Convenções

| Item | Regra |
|---|---|
| Base | URL do backend (HTTPS). Prefixo `/v2`. |
| Autenticação | `Authorization: Bearer <Firebase ID token>` em toda rota `/v2/*`. O `uid` vem **só** do token. |
| Idioma | `Accept-Language: pt-BR` ou `en`. O backend usa para textos gerados (fala de abertura, sugestões, mensagens de erro). Padrão `en`. |
| Fuso | `X-Timezone: America/Sao_Paulo` (IANA), enviado pelo app. Define o "dia" do baralho. Padrão `America/Sao_Paulo`. |
| Formato | JSON, campos em `camelCase`. Datas em ISO-8601 com fuso (`2026-10-01T03:00:00Z`). |
| Enums | Nomes exatos do app: `Origin`, `PowerFamily`, `Team`, `Style` (lista em §7). `choice`: `PASS` / `ASSEMBLE`. |
| Campos ausentes | Fato que a fonte não tem **não vem** no JSON (nunca `null` inventado, nunca string vazia). |
| Idempotência | `POST /v2/decisions` e `POST /v2/connections/{id}/messages` aceitam `Idempotency-Key` (uuid do app); repetir a mesma chave devolve a mesma resposta. Na mensagem, repetir também retoma o envio que falhou ou se perdeu (ver §4). |
| Compatibilidade | **Nunca** aparece antes da conexão: sem faixa, sem porcentagem, em nenhuma rota. |

## 2. Leitura e escrita: quem faz o quê

- **Escrita de tudo que tem regra** (decisões, mensagens, conexões, baralho, conta): **só pelo backend**.
- **Leitura dos dados do próprio usuário**: o app **escuta o Firestore** (tempo real e cache offline), porque o app já é todo em fluxos (`Flow`) e o aviso de nova mensagem depende disso:
  - `users/{uid}/matches` → lista de conversas e conexões novas;
  - `users/{uid}/matches/{characterId}/messages` → conversa aberta;
  - `users/{uid}` → perfil (com `profileStyle`) e preferências.
- **Escrita direta do app no Firestore**, validada pelas regras: só perfil (incluindo `profileStyle`), preferências e `aiConsent` em `users/{uid}`; `lastReadAt` e `profileUnlockSeenAt` em `matches/*`.
- Catálogo e pré-visualização vêm **do backend** (`/v2/characters/{id}`), para a bio não vazar antes da conexão.

## 3. Objetos

### DeckCard
```json
{ "characterId": "storm", "name": "Storm", "imageUrl": "https://…", "tagline": "Ororo Munroe controla o clima.", "traitsInCommon": ["Mutant", "XMen"] }
```
`traitsInCommon` na ordem Origin → Powers → Teams → Style, no máximo 3 no card (o app corta). `tagline` é a primeira frase da bio (até 140 caracteres) e some quando não há bio.

### Deck
```json
{
  "date": "2026-10-01",
  "cards": [DeckCard],
  "remaining": 18,
  "total": 40,
  "nextDeckAt": "2026-10-02T03:00:00Z",
  "canUndo": true
}
```
- `cards`: até 40 por dia, **sorteados de novo a cada chamada** e diferentes para cada pessoa. Metade vem da compatibilidade com as preferências; a outra metade, do gosto aprendido pelas decisões. Os cards não indicam de qual metade vêm.
- `nextDeckAt`: meia-noite do próximo dia no fuso do usuário (a contagem regressiva da tela "Deck complete").
- `cards` vazio = baralho completo.

### AssembleAccepted (resposta de um Assemble, `202`)
```json
{ "characterId": "storm", "status": "pending | matched | not_matched | failed" }
```
- Num Assemble novo, `status` vem `pending`: a decisão já está gravada (o personagem não volta ao baralho) e a fila decide o match.
- Com match, a conexão aparece em `matches/{characterId}` no Firestore (com `score`, `whyYouMatch`, nome, imagem e a fala de abertura); o app abre o pop-up a partir dela. Sem match, nada aparece.
- O mesmo `status` fica em `decisions/{characterId}`. `failed` (com `errorCode`) é retomado sozinho ao abrir o baralho, até 3 tentativas, ou ao repetir com a mesma `Idempotency-Key`.

### Message
```json
{
  "id": "m_01J…",
  "connectionId": "storm",
  "author": "USER | CHARACTER",
  "text": "…",
  "createdAt": "2026-10-01T15:04:00Z",
  "fictional": true,
  "blocked": false,
  "status": "pending | sent | blocked | failed"
}
```
`fictional` é sempre `true` em mensagem do personagem (o app mostra "AI-generated · fictional").

`status` (também gravado no documento da mensagem do usuário no Firestore):

| `status` | Significado | O app faz |
|---|---|---|
| `pending` | resposta na fila; o documento ainda **não tem o texto** (`text = ""`) | mostra a cópia local da mensagem e o "digitando" |
| `sent` | respondida; o documento tem o texto e `replyId` | mensagem normal |
| `blocked` | recusada pelo guardrail; o texto nunca é gravado (`blockReason` diz o motivo). Em `self_harm` (CVV 188) e `sexual_violence` (180, 100 e 190), a resposta é um texto fixo de acolhimento com os canais de ajuda | balão com aviso |
| `failed` | a resposta não pôde ser gerada (`errorCode`, hoje sempre `provider_unavailable`) | "Try again": reenvia com a **mesma** `Idempotency-Key` |

Na mensagem do **personagem**, `status` só muda em "gerar outra resposta": `pending` enquanto o texto novo é gerado ("digitando"; o texto anterior continua no documento; `regenerateRequestedAt` diz quando foi pedido, e o app desiste de esperar depois de 3 minutos) e `failed` se não deu certo (o texto anterior continua; `errorCode` diz o motivo).

Mensagem sem `status` (gravada antes desta versão) vale como `sent`.

### AcceptedMessage (resposta do envio)
```json
{ "userMessage": Message }
```
- `userMessage.status` é `pending` num envio novo. A resposta do personagem **não vem aqui**: chega pelo Firestore (`messages`), junto com as `suggestions` no documento da conexão.
- `suggestions`: **3** perguntas curtas, no idioma do `Accept-Language`, gravadas em `matches/{id}.suggestions` a cada resposta. Se a geração falhar, o backend usa modelos fixos a partir dos traços, nunca uma lista vazia sem motivo.

### Overture (documento `overtures/{characterId}`, lido do Firestore)
Personagem que "tentou um Assemble" com o usuário sem ele saber. A cada 30 minutos (`OVERTURE_INTERVAL_MINUTES`, 0 desliga) o backend sorteia, para cada usuário ativo, um personagem que ele ainda não decidiu e faz a conta do Assemble pelo lado do personagem (compatibilidade, afinidade e sorte).

| Campo | Uso no app |
|---|---|
| `status` | `pending`: o personagem quer dar Assemble, mostrar "fulano quer dar assemble com você" dentro do app; `accepted`, `declined`: o usuário respondeu; `skipped`: sem match, ignorar |
| `createdAt` | ordenação |

- Só um `pending` por usuário. Não há notificação fora do app.
- O usuário responde pelo fluxo normal: `POST /v2/decisions` do personagem. `ASSEMBLE` num `pending` **sempre** vira conexão e não conta no limite de Assembles; `PASS` marca `declined`.
- `POST /jobs/overtures` roda uma rodada na hora (X-Jobs-Key).

### Connection (documento `matches/{characterId}`, lido do Firestore)
| Campo | Uso no app |
|---|---|
| `characterName`, `characterNamePtBR`, `imageUrl` | linha da lista e fileira de conexões novas. `characterName` é o nome original; `characterNamePtBR` só existe quando há nome consagrado em português (tabela curada). O app usa o segundo em pt-BR e, sem ele, o primeiro. |
| `score` | pílula de score na lista |
| `createdAt`, `lastMessageAt`, `lastMessagePreview` | ordenação e prévia |
| `lastReadAt` | "não lida" = existe mensagem do personagem depois disso |
| `userMessageCount` | **0 = conexão nova** (fileira no topo); campo novo, mantido pelo backend |
| `suggestions` | as 3 sugestões atuais da conversa (campo novo; atualizadas a cada resposta e na fala de abertura) |
| `profileUnlockSeenAt` | animação de desbloqueio do perfil só uma vez |
| `hidden` | conversa apagada (não aparece) |

### CharacterPreview / CharacterProfile
```json
// sem conexão
{ "characterId": "storm", "name": "Storm", "imageUrl": "…", "traitsInCommon": ["Mutant", "XMen"], "connected": false }

// com conexão
{
  "characterId": "storm", "name": "Storm", "imageUrl": "…", "connected": true,
  "connectionId": "storm", "score": 82,
  "whyYouMatch": [{ "category": "origin", "traits": ["Mutant"] }, { "category": "teams", "traits": ["XMen"] }],
  "facts": {
    "realName": "Ororo Munroe", "aliases": ["Windrider", "Mistress of the Elements"],
    "origin": "Mutant", "powers": ["Energy", "Flight"], "teams": ["XMen"], "alignment": "Good",
    "placeOfBirth": "New York, New York", "occupation": "Adventurer", "base": "Xavier Institute, …",
    "firstAppearance": "Giant-Size X-Men #1", "issueAppearances": 2900, "bio": "…",
    "relatives": "David Munroe (father, deceased), …",
    "powerstats": { "intelligence": 75, "strength": 10, "speed": 47, "durability": 30, "power": 88, "combat": 75 },
    "appearance": { "gender": "Female", "race": "Mutant", "heightCm": 180, "weightKg": 57, "eyeColor": "Blue", "hairColor": "White" }
  },
  "factSources": { "realName": "ComicVine", "aliases": "SuperheroApi", "powerstats": "SuperheroApi", "…": "…" },
  "sources": [{ "name": "Comic Vine", "url": "https://comicvine.gamespot.com/…" },
              { "name": "Superhero API", "url": "https://akabab.github.io/superhero-api/" }],
  "teammates": [{ "characterId": "jean-grey", "name": "Jean Grey", "imageUrl": "…", "connected": true }],
  "compareWith": [{ "characterId": "iron-man", "name": "Iron Man", "powerstats": { "intelligence": 100, "…": 0 } }]
}
```
- Sem conexão **não** vêm bio, poderes, equipes, primeira aparição nem nada dos campos novos (a pré-visualização mostra só espaços trancados).
- `facts`: só os campos que a fonte tem. `powerstats` vem com os 6 valores (0–100) ou não vem. Em `appearance`, cada campo é opcional.
- **Idioma:** com `Accept-Language: pt-BR`, o `name` do personagem vem da tabela curada (`data/names_ptbr.json`) e, sem entrada, no original. Em `facts`, os textos longos (`bio`, `occupation`, `base`, `placeOfBirth`, `relatives`) vêm traduzidos por IA quando a tradução existe, e `translatedFields` lista quais foram traduzidos (o app pode mostrar um selo "tradução automática"). `aliases`, `firstAppearance` e todos os outros campos ficam no original. Sem tradução guardada, o texto original é devolvido e `translatedFields` não vem.
- `factSources`: a fonte de cada fato presente (`ComicVine`, `SuperheroApi`, `MarvelDatabase`, `FiveThirtyEight`). O app mostra um selo por fato e lista as fontes no rodapé.
- `teammates`: até 8 personagens do catálogo que dividem uma equipe (sem contar `Solo`), os conectados primeiro. Lista vazia = o app mostra "nenhum colega no catálogo".
- `compareWith`: as conexões do usuário que têm `powerstats` (sem o próprio personagem). É usada na comparação do radar.
- Substitui os antigos `source`/`sourceUrl` (o crédito fica em `sources`).

### profileStyle (em `users/{uid}`, escrito pelo app)
```json
{ "cover": "Comic", "accent": "Violet", "frame": "Hexagon", "prompt": "IdealTeam",
  "promptAnswer": "X-Men, com a Storm na liderança",
  "featuredConnections": ["storm", "rocket"], "featuredBadges": ["Crossover"] }
```
- As regras validam enums, `promptAnswer` ≤ 80 e listas ≤ 3. Moldura bloqueada e destaques inválidos **não** são barrados no banco: o app limpa na exibição (o perfil só é visto pelo dono). 
- O arquétipo ("Estilo · Origem") é calculado pelo app a partir das preferências e não é guardado.

### UserStats
```json
{ "connections": 7, "messagesSent": 23, "charactersSeen": 41, "distinctTeams": 3 }
```
Alimenta o cabeçalho do menu lateral e as conquistas. As regras das conquistas ficam **no app** (`AchievementRules`); o backend só conta.

## 4. Rotas

| Método | Rota | Corpo | Resposta | Tela do app |
|---|---|---|---|---|
| GET | `/health` | — | `{ "status": "ok" }` | — |
| GET | `/ready` | — | `{ "laya": "warm \| loading \| off", "queues": { … } }` (`503` enquanto o Laya carrega) | — (monitoramento) |
| GET | `/v2/deck` | — | `Deck` | Discover, "Deck complete" |
| POST | `/v2/decisions` | `{ "characterId", "choice": "PASS" \| "ASSEMBLE" }` | PASS: `204`; ASSEMBLE: `202` `AssembleAccepted` | swipe, botões, pré-visualização |
| POST | `/v2/decisions/undo` | — | `DeckCard` (volta ao topo) | botão Undo |
| GET | `/v2/characters/{id}` | — | `CharacterPreview` ou `CharacterProfile` | pré-visualização, perfil |
| POST | `/v2/connections/{id}/messages` | `{ "text" }` (1–1000 caracteres) | `202` `AcceptedMessage` | conversa |
| POST | `/v2/connections/{id}/messages/regenerate` | — | `202` `{ reply }` | "Gerar outra resposta" |
| POST | `/v2/connections/{id}/messages/rewind` | `{ "messageId" }` | `204` | "Voltar a conversa" |
| GET | `/v2/onboarding/reaction-cards` | — | `{ cards: [DeckCard] }` | cadastro: rodada "este ou aquele" |
| PUT | `/v2/taste-signals/{id}` | `{ "liked": true }` | `204` | cadastro: ensina o gosto, não é decisão |
| POST | `/v2/account/email-verification` | — | `204` | tela "Confirme o seu e-mail" (503: o app usa o e-mail do Firebase) |
| POST | `/v2/me/photo/signature` | — | `{ uploadUrl, fields }` | foto do perfil no Cloudinary (503 se não configurado) |
| GET | `/v2/me/stats` | — | `UserStats` | menu lateral, conquistas |
| POST | `/v2/chats/hide` | — | `204` | Configurações → Delete chats |
| POST | `/v2/account/deactivate` | — | `{ "purgeAt": "…" }` | Configurações → Delete account |
| POST | `/v2/account/reactivate` | — | `204` | tela de conta desativada (a criar) |
| POST | `/jobs/ingest`, `/jobs/personas`, `/jobs/translations`, `/jobs/purge` | — | `202` | só GitHub Actions (`X-Jobs-Key`) |

Notas:
- **Conexão e fala de abertura (assíncrono)**: o Assemble responde `202` na hora; a fila calcula a afinidade, decide o match e, com match, grava a conexão e a primeira mensagem do personagem (com `suggestions`). O app abre o pop-up F quando a conexão aparece no Firestore, e a conversa já tem a fala ao entrar. Limite de 60 Assembles por hora; fila cheia dá `503` com `Retry-After`.
- **Envio de mensagem (assíncrono)**: o backend grava a mensagem do usuário como `pending` (sem o texto) e responde `202` na hora; uma fila gera a resposta e grava a troca no Firestore. Uma resposta pendente por conversa: outra mensagem antes dela dá `409 reply_pending`. Repetir com a mesma `Idempotency-Key` devolve o estado gravado; se ele for `failed`, ou `pending` perdido num reinício do servidor, a mensagem volta para a fila (conta no limite por hora). Se a conversa for apagada ou voltada enquanto a resposta está na fila, a resposta é descartada.
- **Undo**: só o último Pass do dia, uma vez. Sem Pass para desfazer → `409 nothing_to_undo`.
- **Pré-visualização a partir do card**: o app já tem `name` e `imageUrl` do `DeckCard` (a arte aparece na hora); a rota completa o resto.
- **Mudança de preferências** no meio do dia **não** refaz o baralho do dia; vale a partir do próximo.
- **Regenerar (assíncrono)**: a última resposta do personagem fica `status = pending` e o backend responde `202` com ela; a fila troca o texto **no mesmo documento** (mesmo `id`) e volta a `sent`, com as `suggestions` novas na conexão. Se falhar, o texto anterior continua e a mensagem fica `failed` (`errorCode`: `provider_unavailable`, ou `blocked_content` se a mensagem do usuário que ela responde passou a ser recusada). Enquanto está na fila, a conversa está ocupada (`409 reply_pending`). **Voltar** apaga tudo depois de uma resposta do personagem; **voltar** apaga tudo depois de uma resposta do personagem (a abertura vale). Mensagem de usuário como alvo dá `400`; id desconhecido, `404`; sem resposta do personagem para trocar, `409 nothing_to_regenerate`.
- **Foto do perfil**: o app envia o JPEG direto ao Cloudinary com os campos assinados e grava a URL `https://res.cloudinary.com/...` em `users/{uid}.avatarPhoto`.
- O app não chama rota para "marcar como lida" nem "desbloqueio visto": grava `lastReadAt` / `profileUnlockSeenAt` direto no Firestore.

## 5. Erros

Formato: `{ "error": "codigo", "message": "texto no idioma do Accept-Language" }`.

| HTTP | `error` | Quando | O app faz |
|---|---|---|---|
| 400 | `invalid_request` | corpo inválido, texto vazio/longo, enum desconhecido | mensagem genérica; não tenta de novo |
| 401 | `unauthenticated` | token ausente/expirado | renova o token uma vez; se falhar, volta ao Login |
| 403 | `account_deactivated` | conta em carência | tela de conta desativada com "Reactivate" |
| 403 | `email_not_verified` | cadastro por e-mail e senha sem o e-mail confirmado | tela "Confirme o seu e-mail" |
| 404 | `not_found` | personagem/conexão não existe | estado "Unavailable" |
| 409 | `nothing_to_undo`, `nothing_to_regenerate`, `already_decided` | Undo sem Pass; nada para regenerar; decisão repetida sem a mesma `Idempotency-Key` | some com o botão / usa a decisão gravada |
| 409 | `reply_pending` | mensagem nova ou "gerar outra resposta" enquanto a conversa tem algo na fila | espera a resposta chegar pelo Firestore |
| 429 | `rate_limited` | limite de mensagens ou de Assembles (60/hora cada) | aviso com o tempo de espera (`Retry-After`) |
| 503 | `provider_unavailable` | modelo/guardrail fora; no envio de mensagem, fila de respostas cheia (com `Retry-After`) | "Try again" na mensagem |

Conteúdo recusado na **saída** do modelo não é erro: vem uma resposta segura, em personagem, com `blocked = true` gravado.

## 6. Fora do contrato (decidido)

- Tema e notificações: ficam no aparelho (DataStore).
- Conquistas: regras no app; o backend só fornece `UserStats`. Sem registro de "desbloqueada em".
- Contador "18/40 hoje" no topo do Discover: não existe (só a tela de baralho completo usa `remaining`/`nextDeckAt`).
- Notificações push, "rever recusados" e personagem que manda tentativa de Assemble: futuro.

## 7. Enums

- Origin: `Human, Mutant, Alien, Robot, Radiation, GodEternal, Animal, Cosmic, Infection, Other`
- PowerFamily: `Strength, Flight, Speed, Mind, Energy, Magic, AgilityCombat, Healing, Shapeshifting, TechGadgets`
- Team: `Avengers, XMen, FantasticFour, Guardians, Shield, Defenders, Solo`
- Style: `Science, Humor, Leadership, Loner, Dark, Idealist, Rebel, Strategist`
- `whyYouMatch[].category`: `origin, powers, teams, style`
- Alignment: `Good, Bad, Neutral`
- Fonte (`factSources`): `ComicVine, SuperheroApi, MarvelDatabase, FiveThirtyEight`
- ProfileCover: `Energy, Halftone, Comic, Night`
- ProfileAccent: `Pink, Red, Blue, Violet, Gold`
- AvatarFrame: `Simple, Ring, Hexagon, Burst` (`Hexagon` exige `TeamUp`, `Burst` exige `Crossover`)
- ProfilePrompt: `DreamPower, IdealTeam, FirstRecruit`
- Conquistas (`featuredBadges`): `FirstConnection, TeamUp, IceBreaker, Storyteller, Explorer, Crossover`
