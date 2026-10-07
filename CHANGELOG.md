# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). As versões contam como um odômetro: cada release é uma grande adição e o número sobe de um em um (`0.0.8`, `0.0.9`, `0.1.0`, `0.1.1`...). Ao chegar em 9, avança a casa seguinte. Correções pequenas entram na release seguinte.

## [0.1.4] - 2026-10-07

Compatível com o app 0.1.3; as novidades visíveis (aviso de personagem que quer dar Assemble) pedem o app 0.1.4.

### Adicionado
- O personagem conhece quem está conversando e não deixa isso explícito: toda resposta, "gerar outra resposta" e a fala de abertura levam notas privadas com o primeiro nome, a bio, o que a pessoa procura, os gostos declarados e o que tem em comum com o personagem. O prompt manda usar isso com naturalidade, sem citar nem dizer que leu o perfil. Bio e "o que procura" passam pelo guardrail; o nome é reduzido a letras. Versão do prompt: `persona-v4`.
- Personagens que tentam um Assemble: a cada 30 minutos (`OVERTURE_INTERVAL_MINUTES`, 0 desliga), cada usuário ativo recebe o sorteio de um personagem que ainda não decidiu, com a mesma conta do Assemble (compatibilidade, afinidade no Laya e sorte). Com match, fica uma proposta pendente em `users/{uid}/overtures` que o app mostra como "fulano quer dar Assemble com você"; dar Assemble nela sempre vira conexão e não conta no limite por hora. `POST /jobs/overtures` roda uma rodada na hora.
- `scripts/load_test.py`: teste de carga do chat, com o Laya real e o modelo simulado.

### Alterado
- O torch usa a cota real de CPU do contêiner (a Discloud mostra 32 núcleos, mas o plano dá cerca de 3,6): cada pergunta ao Laya caiu de 959 ms para cerca de 265 ms.
- O Laya só recebe as perguntas cujo indício aparece no texto (autoagressão, jailbreak, violência sexual e, na saída, nocivo e canônico): uma mensagem de chat passou de 8 para cerca de 2,7 perguntas, sem mudar nenhum veredito nas frases testadas.
- A fila do chat tem 12 consumidores (eram 6). Com 50 usuários conversando e um modelo de 8 s, a resposta leva cerca de 9 s no teste de carga (antes, 98 s).
- Relato de violência sexual passa a receber acolhimento com o Ligue 180, o Disque 100 e o 190, sem chamar o modelo.

## [0.1.3] - 2026-10-07

**Exige o app 0.1.3 ou mais novo:** o envio de mensagem, "gerar outra resposta" e o Assemble mudaram de contrato.

### Adicionado
- Deploy na Discloud (`https://assemble.discloud.dev`), com deploy automático a cada push na `main` (veja `docs/discloud.md`).
- Filas em segundo plano para o trabalho pesado: a resposta do chat, "gerar outra resposta" e o Assemble respondem `202` na hora, e o resultado chega ao app pelo Firestore. O proxy da Discloud corta pedidos em cerca de 30 s, e essas rotas passavam disso; era o erro de "tentar de novo" no chat e o card que voltava ao baralho.
- Estado gravado nas mensagens (`pending`, `sent`, `blocked`, `failed`) e nas decisões de Assemble (`pending`, `matched`, `not_matched`, `failed`). A mensagem pendente é gravada sem o texto: ele só vai para o Firestore depois do filtro de entrada.
- Retomada: repetir com a mesma `Idempotency-Key` retoma o que falhou ou se perdeu num reinício do servidor; Assembles pendentes ou com falha também são retomados ao abrir o baralho (até 3 tentativas).
- Encaminhamento para relatos de violência sexual: resposta fixa de acolhimento com o Ligue 180, o Disque 100 e o 190, sem chamar o modelo e sem guardar o texto, como já acontecia com autoagressão e o CVV.
- `GET /ready`: responde `503` enquanto o Laya carrega e mostra o tamanho das filas. O log registra as filas ocupadas a cada minuto e, no boot, a velocidade do Laya na máquina.
- Limite de 60 Assembles por hora por usuário.
- Script que cria uma conta de demonstração com o e-mail já confirmado.
- As regras do Firestore aceitam as recompensas das conquistas v2 e o título do perfil.

### Alterado
- O Laya faz uma inferência por vez, com prioridade para os filtros do chat (várias em paralelo levavam mais de 150 s cada), e cada checagem faz uma inferência só.
- As respostas do chat são geradas por 6 consumidores em paralelo; cada conversa tem no máximo uma resposta na fila (`409 reply_pending`).
- O token do Firebase verificado é reaproveitado por até 5 minutos, em vez de consultar o Google a cada pedido; os vereditos do Laya sobre a bio e o "o que procura" ficam em cache. Os dois caches guardam só o hash SHA-256.
- O registro de acesso (Marco Civil) é gravado depois da resposta, inclusive quando a rota termina em erro.
- O baralho lê as decisões do usuário uma vez só por abertura.
- Um relato como "ele me forçou a fazer sexo" deixa de ser recusado como pedido sexual.
- E-mail de verificação com o logo do Assemble e layout refinado.
- Laya atualizado para 0.3.28.

### Removido
- O erro `422 blocked_content`: a recusa vem como `status = blocked` no Firestore.

### Corrigido
- Cache do Hugging Face dentro da pasta do projeto e `main.py` na raiz, para a API subir na Discloud.

## [0.1.2] - 2026-10-05

### Adicionado
- Verificação de e-mail no cadastro por e-mail e senha: a conta só usa o app depois de confirmar o e-mail. Enquanto isso, as rotas respondem `403 email_not_verified` (o login com Google já vem confirmado; `REQUIRE_EMAIL_VERIFICATION` desliga o bloqueio).
- `POST /v2/account/email-verification`: manda o link de confirmação em **HTML com o design system do app**, por SMTP (uma conta do Gmail com senha de app serve, sem domínio próprio). Sem SMTP, o app usa o e-mail padrão do Firebase. Reenvio limitado a um por minuto.
- Elogios simples e educados são recebidos de braços abertos, no jeito de falar do personagem: um simpático agradece com simpatia, e um arrogante, como o Ultron, agradece em tom de superioridade.
- Insinuações sexuais sem termo explícito são recusadas pelo próprio personagem, na sua voz, deixando claro que os dois não têm essa intimidade.

### Alterado
- Só o pedido sexual explícito é barrado pelo guardrail, por regra de palavras; a pergunta sexual do Laya saiu (dava 0,01 para frases explícitas).
- Na saída, os sinais "nocivo" e "canônico" do Laya só valem com uma palavra-indício: respostas carinhosas inocentes eram trocadas pela recusa genérica.
- A documentação diz "Assemble" e "conexão" no lugar de "match" (nomes de campos e variáveis do contrato continuam iguais).

## [0.1.1] - 2026-10-05

### Adicionado
- Foto do perfil no Cloudinary, com envio assinado pelo servidor (`POST /v2/me/photo/signature`). Sem as variáveis `CLOUDINARY_*`, o app segue guardando a foto no Firestore. A foto é apagada do Cloudinary na exclusão definitiva da conta.
- `LICENSE` (MIT), `CHANGELOG.md` e `docs/api-contract.md` atualizado.

### Alterado
- O projeto passou a se chamar **assemble-api** (pacote, serviço do Cloud Run e documentação).
- A documentação de trabalho saiu do repositório; ficam só README, contrato da API e guias de execução.

### Corrigido
- CI: o `setup-uv` foi fixado em `v10.2.0`, porque a action não tem a tag flutuante `v10`.

## [0.1.0] - 2026-10-05

### Adicionado
- Memória da conversa: o que sai da janela de mensagens vira um resumo rolante, atualizado em segundo plano com um modelo de retenção zero. Em teste com 100 mensagens, o personagem lembrou 6 de 6 fatos plantados no começo (contra 0 de 6 sem o resumo).

### Alterado
- A janela de histórico do chat passou de 20 para 40 mensagens.

## [0.0.9] - 2026-10-05

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

## [0.0.8] - 2026-10-05

### Adicionado
- Baralho de 40 cards por dia, diferente para cada pessoa e sorteado de novo a cada abertura. Metade vem da compatibilidade e metade do gosto aprendido pelas decisões.

### Alterado
- Os personagens mais compatíveis pesam mais no sorteio.

## [0.0.7] - 2026-10-05

### Adicionado
- Nota de condução por turno: o servidor alterna pergunta e afirmação e puxa assunto novo, para o chat ser uma troca e não só perguntas e respostas.
- Tempo de cada etapa do chat e do Assemble nos logs; controle do esforço de raciocínio de cada modelo (respostas de 2 a 4 s).

### Corrigido
- A primeira mensagem não estoura o tempo: o Laya aquece com uma inferência real na partida.
- Cada `Idempotency-Key` é processada uma vez por vez, o que evita mensagem duplicada ao tentar de novo.

## [0.0.6] - 2026-10-04

### Adicionado
- Regenerar a última resposta e voltar a conversa (`/messages/regenerate` e `/messages/rewind`).
- Compatibilidade com "Qualquer" neutro e rivalidades entre grupos.
- Foto do perfil permitida nas regras do Firestore.

## [0.0.5] - 2026-10-04

### Adicionado
- Chat com jeito de conversa de mensagens e fichas de persona próprias para chat (`persona-sheet-v2`).
- Frase curta (`tagline`) em cada card do baralho.
- Guardrail calibrado com frases reais: limiares por motivo e regras de palavras-chave para dados pessoais e autoagressão.
- O servidor recusa na partida modelos que treinam com os dados (`contributor`) no chat.

### Corrigido
- Jobs de IA mais robustos: JSON tolerante, novas tentativas, respostas em streaming contra o erro 524, falhas isoladas do provedor e traduções campo a campo.
- Traduções em paralelo, opcionais (`TRANSLATION_CONCURRENCY`).

## [0.0.4] - 2026-10-03

### Adicionado
- Nomes dos personagens em português (tabela curada) e tradução por IA dos textos longos do perfil.
- Nomes de busca e IDs fixos do tier A na Comic Vine, e ferramenta `find_character`.
- Script de smoke test com login real do Firebase.

## [0.0.3] - 2026-10-02

### Adicionado
- Testes das regras do Firestore no emulador (perfil, `profileStyle`, conexões e conta desativada).
- CI com testes a cada push e deploy opcional no Google Cloud Run, com a imagem trazendo os pesos do Laya.
- Guia para rodar o backend no PC com um túnel ngrok; jobs e deploy na nuvem passam a ser manuais.

### Alterado
- Valores em branco no `.env` valem como ausentes; o litellm não carrega mais o `.env`.

## [0.0.2] - 2026-10-01

### Adicionado
- Enriquecimento pela Superhero API, com casamento manual, por Wikidata e automático, limpeza dos dados, fonte de cada fato e fila de revisão.
- Perfil do personagem em abas (atributos, aparência, colegas de equipe, comparação) e regras do `profileStyle` do usuário.

## [0.0.1] - 2026-10-01

Primeira versão da API.

### Adicionado
- API V2 em FastAPI: login pelo token do Firebase, bloqueio de conta desativada e registros de acesso.
- Compatibilidade entre preferências e personagem, repositórios do Firestore e regras de segurança.
- Ingestão da Comic Vine com tabelas de mapeamento e níveis de qualidade.
- Baralho diário, decisões (Pass e Assemble) idempotentes e Undo.
- Fichas de persona geradas por LiteLLM e chat com IA, com fallback de modelo, guardrail Laya e fala de abertura ao virar conexão.
- Afinidade da persona (Laya) na decisão do Assemble, com modo degradado.
- Conversas, perfil e prévia do personagem e estatísticas do usuário.
- Desativar e reativar conta com 30 dias de carência, ocultar conversas e job de expurgo (LGPD e Marco Civil).
