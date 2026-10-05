# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). O projeto segue [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [0.1.0] - 2026-10-05

Primeira versão com o fluxo completo funcionando de ponta a ponta com o app Android.

### Adicionado
- API V2 em FastAPI: baralho diário, decisões (Pass e Assemble) com Undo, conexões, chat, perfil do personagem e do usuário, estatísticas e conta (ocultar conversas, desativar e reativar). Contrato em `docs/api-contract.md`.
- Login pelo token do Firebase e dados no Firestore, com regras de segurança testadas no emulador.
- Catálogo de 106 personagens: ingestão da Comic Vine, Marvel Database e Superhero API, com fichas de persona e traduções para pt-BR geradas por job.
- Compatibilidade entre preferências e personagem, com rivalidades entre grupos, e decisão de match que combina compatibilidade, afinidade (Laya) e acaso.
- Baralho de 40 cards por dia, único para cada pessoa e sorteado de novo a cada abertura: metade pelas preferências, metade pelo gosto aprendido nas decisões (agora também por herói/vilão e gênero).
- Cadastro: rodada de reação "este ou aquele" (os sinais ensinam o gosto sem virar decisão) e a frase opcional "o que você procura numa conversa?".
- Chat com IA via LiteLLM (modelos de retenção zero), tom de conversa de mensagens, teto de palavras por resposta e nota de condução por turno.
- Regenerar a última resposta e voltar a conversa.
- Memória da conversa: resumo rolante do que saiu da janela de 40 mensagens, em segundo plano.
- Guardrail Laya: autoagressão (com encaminhamento ao CVV 188), dados pessoais, jailbreak, conteúdo sexual, injeção em textos de fonte e saída fora de personagem. Romance não é bloqueado: declarações de amor recebem uma resposta carinhosa.
- Foto do perfil no Cloudinary com envio assinado pelo servidor (opcional).
- Jobs de ingestão, fichas, traduções e expurgo (LGPD e Marco Civil), com execução manual pelo GitHub Actions.
