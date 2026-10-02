# Deploy no Google Cloud Run

O workflow `.github/workflows/deploy.yml` testa, constrói a imagem, envia ao Artifact Registry e publica no Cloud Run a cada push na `main`. A autenticação usa Workload Identity Federation: nenhuma chave do Google fica no GitHub.

Os comandos abaixo rodam no **Cloud Shell** (ícone `>_` no topo do console do Google Cloud), que já tem o `gcloud` logado. Troque os valores em maiúsculas.

## 1. Projeto e faturamento

1. Use o **mesmo projeto do Firebase** (`assemble-app`): todo projeto do Firebase é um projeto do Google Cloud, e ele aparece em console.cloud.google.com. Anote o **ID do projeto**.
2. Vincule uma conta de faturamento (o Google pede cartão para ativar a camada gratuita). No Firebase isso muda o projeto para o plano Blaze, que mantém a cota gratuita do Firestore e do Auth.
3. Em *Faturamento → Orçamentos e alertas*, crie um orçamento de **US$ 1** com alertas em 50% e 100%. O Cloud Run não para sozinho quando o orçamento estoura; o alerta só avisa.

## 2. APIs e repositório de imagens

```bash
gcloud config set project ID_DO_PROJETO
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com
gcloud artifacts repositories create assemble --repository-format=docker --location=us-central1
```

Use `us-central1`: é uma região elegível à camada gratuita e fica perto do Firestore (`nam5`).

## 3. Segredos

Crie os quatro segredos. Cada comando pede o valor na entrada padrão; cole e termine com Ctrl+D.

```bash
gcloud secrets create assemble-firebase-service-account --data-file=-
gcloud secrets create assemble-comicvine-api-key --data-file=-
gcloud secrets create assemble-commandcode-api-key --data-file=-
gcloud secrets create assemble-jobs-key --data-file=-
```

- `assemble-firebase-service-account`: o conteúdo inteiro do JSON da conta de serviço do Firebase.
- `assemble-jobs-key`: um segredo aleatório longo. Guarde o mesmo valor para o GitHub (passo 6).

Dê ao serviço do Cloud Run permissão para ler os segredos (a conta padrão do Compute Engine é a que executa o serviço):

```bash
PROJECT_NUMBER=$(gcloud projects describe ID_DO_PROJETO --format='value(projectNumber)')
gcloud projects add-iam-policy-binding ID_DO_PROJETO \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

## 4. Conta de serviço do deploy e Workload Identity

```bash
gcloud iam service-accounts create github-deploy
SA="github-deploy@ID_DO_PROJETO.iam.gserviceaccount.com"

for ROLE in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding ID_DO_PROJETO --member="serviceAccount:$SA" --role=$ROLE
done

# Permite que o deploy crie revisões que rodam com a conta padrão do Compute Engine.
gcloud iam service-accounts add-iam-policy-binding \
  ${PROJECT_NUMBER}-compute@developer.gserviceaccount.com \
  --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser

gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='USUARIO_GITHUB/NOME_DO_REPOSITORIO'"

gcloud iam service-accounts add-iam-policy-binding $SA \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/USUARIO_GITHUB/NOME_DO_REPOSITORIO"
```

A condição do provedor restringe o acesso a **este repositório**. Sem ela, qualquer repositório do GitHub poderia pedir credenciais.

Pegue o nome completo do provedor, que vai para o GitHub:

```bash
gcloud iam workload-identity-pools providers describe github-provider \
  --location=global --workload-identity-pool=github --format='value(name)'
```

## 5. Firestore

Com o mesmo projeto, o backend acessa o Firestore pelo JSON da conta de serviço do passo 3. Confirme que o banco foi criado em `nam5` e que as regras de `firestore.rules` foram publicadas.

## 6. Variáveis do GitHub

No repositório, em *Settings → Secrets and variables → Actions → Variables*:

| Variável | Valor |
|---|---|
| `GCP_PROJECT_ID` | ID do projeto do Cloud Run |
| `GCP_REGION` | `us-central1` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | o nome completo do passo 4 (`projects/…/providers/github-provider`) |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `github-deploy@ID_DO_PROJETO.iam.gserviceaccount.com` |
| `COMMANDCODE_BASE_URL` | `https://api.commandcode.ai/provider/v1` |
| `CHAT_MODEL` / `CHAT_FALLBACK_MODEL` / `PERSONA_MODEL` | ids dos modelos |

Em *Secrets*, para os jobs agendados (`.github/workflows/jobs.yml`):

| Secret | Valor |
|---|---|
| `JOBS_KEY` | o mesmo valor do segredo `assemble-jobs-key` |
| `ASSEMBLE_API_URL` | a URL do serviço, que o primeiro deploy mostra (`https://assemble-backend-….run.app`) |

## 7. Primeiro deploy

Faça push na `main` ou rode *Actions → Test and deploy → Run workflow*. O primeiro build leva alguns minutos (o `torch` e os pesos do Laya entram na imagem). Ao fim, o log do passo de deploy imprime a URL do serviço. Teste:

```bash
curl https://URL_DO_SERVICO/health
```

## Custos e limites

- A camada gratuita do Cloud Run tem cota mensal de requisições, vCPU-segundos e GiB-segundos. Confira os valores atuais em cloud.google.com/run/pricing: com a CPU sempre alocada (`--no-cpu-throttling`), a cobrança segue as regras de faturamento por instância, com cota gratuita menor.
- O serviço escala a zero, então uma instância parada não gera custo. Depois de uma requisição, a instância fica de pé por alguns minutos.
- A imagem tem cerca de 2 GB. O Artifact Registry cobra armazenamento acima de 0,5 GB. Para limitar, apague imagens antigas ou crie uma política de limpeza.
- `--max-instances=1` limita o gasto e mantém coerentes o limite de mensagens e o bloqueio dos jobs, que vivem na memória do processo.
- Se o serviço reiniciar por falta de memória, suba para `--memory=4Gi` no workflow.
- A primeira requisição após um período parado leva alguns segundos (partida a frio). Os jobs agendados já tentam de novo por até 4 minutos.
