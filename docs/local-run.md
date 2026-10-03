# Rodar o backend no PC e acessar pelo celular (ngrok)

O backend roda no PC e o ngrok o expõe numa URL pública HTTPS, que o app Android usa como URL base. O Android bloqueia `http` puro por padrão; o túnel já entrega HTTPS.

Limites do plano gratuito do ngrok (conferidos em ngrok.com/docs/pricing-limits/free-plan-limits): **1 domínio fixo**, 1 GB de transferência e 20.000 requisições por mês. Para um projeto de disciplina, sobra. A página de aviso do ngrok aparece só para tráfego de navegador; chamadas do app não são afetadas.

## 1. Pré-requisitos (uma vez)

- Python 3.12 e [uv](https://docs.astral.sh/uv/): `uv sync` na raiz do projeto.
- Arquivo `.env` na raiz, preenchido a partir de `.env.example`. Ele fica fora do git.
  - `FIREBASE_SERVICE_ACCOUNT_JSON`: o conteúdo do JSON da conta de serviço, **em uma linha**. No PowerShell:
    ```powershell
    (Get-Content .\caminho\chave.json -Raw | ConvertFrom-Json | ConvertTo-Json -Compress)
    ```
    Copie a saída para a linha do `.env`, **entre aspas simples**:
    ```
    FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
    ```
    As aspas simples preservam as quebras de linha da chave privada (a sequência de dois caracteres, barra invertida e n). O JSON baixado não deve ficar dentro da pasta do projeto.
  - `COMICVINE_API_KEY`, `COMMANDCODE_API_KEY`, `COMMANDCODE_BASE_URL`.
  - `CHAT_MODEL`, `CHAT_FALLBACK_MODEL`, `PERSONA_MODEL`: ids de `GET https://api.commandcode.ai/provider/v1/models`.
  - `JOBS_KEY`: um segredo aleatório longo.
    ```powershell
    python -c "import secrets; print(secrets.token_urlsafe(48))"
    ```
- Conta gratuita no ngrok (ngrok.com), instalação do agente e o authtoken, uma vez:
  ```powershell
  winget install ngrok.ngrok
  ngrok config add-authtoken SEU_AUTHTOKEN
  ```
  O authtoken está em *Getting Started → Your Authtoken* no painel. O domínio fixo da conta está em *Domains*.

## 2. Subir o backend

Terminal 1, na raiz do projeto:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Na primeira vez, o Laya baixa os pesos (cerca de 650 MB) em segundo plano. Até terminar, o chat e o match esperam o carregamento.

Terminal 2, o túnel (troque pelo domínio da sua conta):

```powershell
ngrok http --url=SEU-DOMINIO.ngrok-free.app 8000
```

Teste de fora do PC (no navegador do celular, com Wi-Fi desligado):

```
https://SEU-DOMINIO.ngrok-free.app/health
```

Deve responder `{"status":"ok"}` (o ngrok pode mostrar a página de aviso antes; clique em continuar).

Esse domínio é a **URL base** do app Android.

## 3. Carga inicial do catálogo

Os jobs não rodam sozinhos. Rode pelo PC, com o backend de pé (a `JOBS_KEY` é a do `.env`):

```powershell
$h = @{ "X-Jobs-Key" = "SUA_JOBS_KEY" }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/jobs/ingest -Headers $h
```

Resposta `202` significa que o job começou; ele continua em segundo plano e o progresso aparece no Terminal 1. Cada execução respeita o limite da Comic Vine (cerca de 190 requisições por recurso), então a ingestão completa leva várias execuções, espaçadas por pelo menos uma hora. Depois, as fichas de persona (20 por execução; repita até acabarem):

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/jobs/personas -Headers $h
```

Depois, a tradução dos textos para pt-BR (também 20 por execução; repita até acabar):

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/jobs/translations -Headers $h
```

`POST /jobs/purge` apaga contas após os 30 dias de carência e logs antigos. Rode de vez em quando.

A ordem é **ingest, depois personas e translations**: ambos usam os dados já ingeridos.

## 4. Pelo GitHub Actions (opcional)

O workflow `Jobs` (*Actions → Jobs → Run workflow*) chama os mesmos endpoints pela URL pública. Exige os secrets `ASSEMBLE_API_URL` (o domínio do ngrok) e `JOBS_KEY`, e o PC ligado com o túnel aberto.

## Limitações

- O PC precisa estar ligado, com o backend e o túnel rodando, sempre que o app for usado.
- O limite de mensagens por hora e o bloqueio dos jobs ficam na memória: reiniciar o backend zera os dois.
- Firewall do Windows: o uvicorn escuta só em `127.0.0.1`, e o ngrok se conecta de dentro do PC, então não é preciso abrir portas.
- Se o ngrok mostrar `ERR_NGROK_…` ao subir, confira o authtoken e se o domínio é o da sua conta.
