# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). O projeto segue [Versionamento Semântico](https://semver.org/lang/pt-BR/): cada versão `0.x.0` marca um conjunto grande de novidades, e as correções pequenas entram na versão seguinte.

## [0.11.0] - 2026-10-05

### Adicionado
- Foto do perfil no Cloudinary, com envio assinado pelo servidor (`POST /v2/me/photo/signature`). Sem as variáveis `CLOUDINARY_*`, o app segue guardando a foto no Firestore. A foto é apagada do Cloudinary na exclusão definitiva da conta.
- `LICENSE` (MIT), `CHANGELOG.md` e `docs/api-contract.md` atualizado.

### Alterado
- O projeto passou a se chamar **assemble-api** (pacote, serviço do Cloud Run e documentação).
- A documentação de trabalho saiu do repositório; ficam só README, contrato da API e guias de execução.

## [0.10.0] - 2026-10-05

### Adicionado
- Memória da conversa: o que sai da janela de mensagens vira um resumo rolante, atualizado em segundo plano com um modelo de retenção zero. Em teste com 100 mensagens, o personagem lembrou 6 de 6 fatos plantados no começo (contra 0 de 6 sem o resumo).

### Alterado
- A janela de histórico do chat passou de 20 para 40 mensagens.

## [0.9.0] - 2026-10-05

### Adicionado
- Rodada de reação do cadastro (`GET /v2/onboarding/reaction-cards`, `PUT /v2/taste-signals/{id}`): os sinais ensinam o gosto sem virar decisão. Herói/vilão e gênero entram no gosto aprendido.
- Frase opcional "o que você procura numa conversa?", usada na afinidade e na fala de abertura.
- Declaração de amor recebe uma resposta carinhosa dizendo que ainda é cedo.

### Alterado
- O guardrail deixa de bloquear romance e passa a barrar termos sexuais explícitos por regra própria.
- A resposta tem um teto de palavras que acompanha o tamanho da mensagem do usuário.

### Corrigido
- Falar de violência sexual ou da morte de outra pessoa não leva mais ao CVV.
- Pedir mensagens menores, ou "fala menos", não é mais tratado como jailbreak.

## [0.8.0] - 2026-10-05

### Adicionado
- Baralho de 40 cards por dia, diferente para cada pessoa e sorteado de novo a cada abertura. Metade vem da compatibilidade e metade do gosto aprendido pelas decisões.

### Alterado
- Os personagens mais compatíveis pesam mais no sorteio.

## [0.7.0] - 2026-10-05

### Adicionado
- Nota de condução por turno: o servidor alterna pergunta e afirmação e puxa assunto novo, para o chat ser uma troca e não só perguntas e respostas.
- Tempo de cada etapa do chat e do match nos logs; controle do esforço de raciocínio de cada modelo (respostas de 2 a 4 s).

### Corrigido
- A primeira mensagem não estoura o tempo: o Laya aquece com uma inferência real na partida.
- Cada `Idempotency-Key` é processada uma vez por vez, o que evita mensagem duplicada ao tentar de novo.

## [0.6.0] - 2026-10-04

### Adicionado
- Regenerar a última resposta e voltar a conversa (`/messages/regenerate` e `/messages/rewind`).
- Compatibilidade com "Qualquer" neutro e rivalidades entre grupos.
- Foto do perfil permitida nas regras do Firestore.

## [0.5.0] - 2026-10-04

### Adicionado
- Chat com jeito de conversa de mensagens e fichas de persona próprias para chat (`persona-sheet-v2`).
- Frase curta (`tagline`) em cada card do baralho.
- Guardrail calibrado com frases reais: limiares por motivo e regras de palavras-chave para dados pessoais e autoagressão.
- O servidor recusa na partida modelos que treinam com os dados (`contributor`) no chat.

### Corrigido
- Jobs de IA mais robustos: JSON tolerante, novas tentativas, respostas em streaming contra o erro 524, falhas isoladas do provedor e traduções campo a campo.
- Traduções em paralelo, opcionais (`TRANSLATION_CONCURRENCY`).

## [0.4.0] - 2026-10-03

### Adicionado
- Nomes dos personagens em português (tabela curada) e tradução por IA dos textos longos do perfil.
- Nomes de busca e IDs fixos do tier A na Comic Vine, e ferramenta `find_character`.
- Script de smoke test com login real do Firebase.

## [0.3.0] - 2026-10-02

### Adicionado
- Testes das regras do Firestore no emulador (perfil, `profileStyle`, conexões e conta desativada).
- CI com testes a cada push e deploy opcional no Google Cloud Run, com a imagem trazendo os pesos do Laya.
- Guia para rodar o backend no PC com um túnel ngrok; jobs e deploy na nuvem passam a ser manuais.

### Alterado
- Valores em branco no `.env` valem como ausentes; o litellm não carrega mais o `.env`.

## [0.2.0] - 2026-10-01

### Adicionado
- Enriquecimento pela Superhero API, com casamento manual, por Wikidata e automático, limpeza dos dados, fonte de cada fato e fila de revisão.
- Perfil do personagem em abas (atributos, aparência, colegas de equipe, comparação) e regras do `profileStyle` do usuário.

## [0.1.0] - 2026-10-01

Primeira versão da API.

### Adicionado
- API V2 em FastAPI: login pelo token do Firebase, bloqueio de conta desativada e registros de acesso.
- Compatibilidade entre preferências e personagem, repositórios do Firestore e regras de segurança.
- Ingestão da Comic Vine com tabelas de mapeamento e níveis de qualidade.
- Baralho diário, decisões (Pass e Assemble) idempotentes e Undo.
- Fichas de persona geradas por LiteLLM e chat com IA, com fallback de modelo, guardrail Laya e fala de abertura no match.
- Afinidade da persona (Laya) na decisão de match, com modo degradado.
- Conversas, perfil e prévia do personagem e estatísticas do usuário.
- Desativar e reativar conta com 30 dias de carência, ocultar conversas e job de expurgo (LGPD e Marco Civil).
