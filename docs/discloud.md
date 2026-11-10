# Deploy na Discloud

A API roda na Discloud como site em `https://assemble.discloud.dev`. A configuração fica em `discloud.config`, na raiz; `.discloudignore` tira do envio o que não roda em produção (testes, docs, scripts, logs).

Exige o plano Platinum ou superior (sites só sobem a partir dele). Com o torch e o Laya, a API usa perto de 3 GB de RAM; o `discloud.config` reserva 4 GB.

## Como sobe

- A Discloud não lista o Python 3.12 entre as versões, e a API exige 3.12. Por isso o `BUILD` instala o `uv`, que baixa o Python 3.12 e instala exatamente o que está no `uv.lock` (o torch só para CPU incluído).
- Na prática, a Discloud ignora o `START` e roda o próprio `uvicorn main:app --host 0.0.0.0`, com o módulo `main` na raiz. O `main.py` da raiz reexporta o `app` de `app/main.py`, aponta o cache do Hugging Face para a pasta do projeto e também roda com `python main.py`.
- Os pesos do Laya (cerca de 650 MB) vêm do Hugging Face no primeiro boot. O log mostra "Laya aquecido" quando o servidor está pronto.

## 1. Subdomínio

No painel da Discloud, registre o subdomínio `assemble` antes do primeiro deploy. Ele precisa bater com o `ID` do `discloud.config`.

## 2. Deploy pelo GitHub Actions

O deploy sai do workflow `.github/workflows/ci-cd.yml`: a cada push na `main`, só depois de `test` e `firestore-rules` passarem, o job `deploy` monta um zip do commit (sem o que o `.discloudignore` tira), envia pela API (`PUT /v2/app/assemble/commit`) e espera o app reiniciar e responder em `/health`. A lógica fica em `.github/scripts/discloud-deploy.sh`.

- O build com torch passa de 2 minutos e o proxy da Discloud corta a resposta antes (502/503/504/524 ou tempo esgotado). Nesses casos o script segue para a espera: consulta `GET /v2/app/assemble/status` até `startedAt` ser posterior ao envio e `/health` responder (até 12 minutos). Qualquer outro código diferente de 200 no commit falha o job.
- Crie o secret `DISCLOUD_API_TOKEN` em Settings → Secrets and variables → Actions (o token vem do painel da Discloud).
- Desligue o **Auto-deploy** do app `assemble` em Discloud → Configurações → *Integração com GitHub* (interruptor da coluna "Auto-deploy"); com ele ligado a Discloud publica cada push na `main` sem esperar a CI.
- Se a URL pública não for `https://assemble.discloud.dev`, defina a variável `DISCLOUD_APP_URL` em Settings → Secrets and variables → Actions → Variables.

## 3. Variáveis de ambiente

Cadastre no painel, no momento do envio. A Discloud gera o `.env` na hora de rodar, e o `app/config.py` já o lê. Nenhum valor fica no repositório.

| Variável | Precisa para | Observação |
|---|---|---|
| `FIREBASE_SERVICE_ACCOUNT_JSON` | subir a API | JSON da conta de serviço **numa linha só**; sem ela o servidor não inicia |
| `COMMANDCODE_API_KEY`, `COMMANDCODE_BASE_URL` | o chat | |
| `CHAT_MODEL` | o chat | `CHAT_FALLBACK_MODEL` é a reserva, opcional |
| `PERSONA_MODEL` | fichas e traduções (jobs) | |
| `COMICVINE_API_KEY` | a ingestão | |
| `JOBS_KEY` | os `/jobs/*` | |
| `SMTP_USER`, `SMTP_PASSWORD` | não | sem eles, o app usa o e-mail padrão do Firebase |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | não | sem eles, a foto fica no Firestore |

## 4. Conferir

```bash
curl -s https://assemble.discloud.dev/health
```

Deve responder `{"status":"ok"}`. Depois disso:

- no app, troque o `BACKEND_URL` do `local.properties` para `https://assemble.discloud.dev`;
- no GitHub da API, troque o secret `ASSEMBLE_API_URL` do workflow `Jobs` para o mesmo endereço.

## Se o deploy falhar

- **Porta 8000 no log:** a Discloud roda o próprio `uvicorn main:app` e ignora o `START`. Se o site não responder, cadastre `UVICORN_PORT=8080` nas variáveis de ambiente (o uvicorn lê a porta dessa variável).
- **`Permission denied: '/.cache'`:** o `main.py` da raiz já manda o cache do Hugging Face para a pasta do projeto; se aparecer, o app não subiu pelo `main.py`.

- **`requirements.txt`:** o deploy pela API exige o arquivo na raiz do zip (o builder da Discloud copia `requirements.txt`). O workflow `ci-cd.yml` o gera na hora do envio com `uv export` a partir do `uv.lock` (mais o índice do PyTorch para CPU, que o export não escreve). Ele precisa trazer as dependências de verdade, porque a Discloud ignora o `START` e roda `uvicorn main:app` direto: um arquivo mínimo (só `uv`) derrubou o app com `"uvicorn": executable file not found in $PATH`. O arquivo não é versionado.
- **Memória:** se o processo morrer ao carregar o Laya, aumente o `RAM`.
