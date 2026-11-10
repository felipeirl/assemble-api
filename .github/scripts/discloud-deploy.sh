#!/usr/bin/env bash
# Deploy na Discloud pela API: envia o zip e espera o app reiniciar e responder.
# Uso: discloud-deploy.sh commit <zip>   |   discloud-deploy.sh wait-ready
# Variáveis: DISCLOUD_API_TOKEN, DISCLOUD_API_URL, DISCLOUD_APP_ID, APP_URL.
set -euo pipefail

: "${DISCLOUD_API_TOKEN:?Secret DISCLOUD_API_TOKEN não configurado}"
: "${DISCLOUD_API_URL:?DISCLOUD_API_URL não definida}"
: "${DISCLOUD_APP_ID:?DISCLOUD_APP_ID não definida}"
: "${APP_URL:?APP_URL não definida}"

PYTHON="${PYTHON:-python3}"
COMMIT_TIMEOUT="${COMMIT_TIMEOUT:-300}"
POLL_INTERVAL="${POLL_INTERVAL:-20}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-36}"
CLOCK_SKEW_SECONDS=5
CURL_TIMEOUT_EXIT=28
STARTED_FILE="${DEPLOY_STARTED_FILE:-${RUNNER_TEMP:-/tmp}/discloud-deploy-started}"

# Mostra o corpo da resposta: JSON formatado (com só o fim do log de build) ou texto cru.
show_body() {
  "$PYTHON" - "$1" <<'PY' 2>/dev/null || head -c 2000 "$1"
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
logs = data.pop("logs", "") or ""
print(json.dumps(data, indent=2, ensure_ascii=False))
if logs:
    print("--- fim do log da Discloud ---")
    print("\n".join(logs.splitlines()[-40:]))
PY
  echo
}

commit() {
  local zip="$1" body code curl_status=0
  [ -f "$zip" ] || { echo "::error::zip não encontrado: $zip"; exit 1; }
  body="$(mktemp)"
  date -u +%s > "$STARTED_FILE"
  code="$(curl --silent --show-error --max-time "$COMMIT_TIMEOUT" \
    --output "$body" --write-out '%{http_code}' \
    -X PUT -H "api-token: $DISCLOUD_API_TOKEN" -F "file=@$zip" \
    "$DISCLOUD_API_URL/app/$DISCLOUD_APP_ID/commit")" || curl_status=$?
  echo "HTTP $code (curl: $curl_status)"
  show_body "$body"

  # O proxy da Discloud corta pedidos longos (o build com torch passa de 2 minutos): nesses
  # casos o build segue do lado deles e quem decide é o wait-ready. Qualquer outra falha aborta.
  case "$code" in
    200)
      echo "Commit aceito pela Discloud."
      ;;
    000)
      if [ "$curl_status" -ne "$CURL_TIMEOUT_EXIT" ]; then
        echo "::error::Falha de rede ao enviar o commit (curl $curl_status)"
        exit 1
      fi
      echo "::warning::Tempo esgotado esperando a resposta; confirmando pelo wait-ready"
      ;;
    502 | 503 | 504 | 524)
      echo "::warning::Proxy da Discloud respondeu HTTP $code; confirmando pelo wait-ready"
      ;;
    *)
      echo "::error::A Discloud respondeu HTTP $code"
      exit 1
      ;;
  esac
}

# Imprime yes/no/unknown: o app reiniciou depois do início do deploy?
restart_state() {
  local body="$1" started="$2" code
  code="$(curl --silent --max-time 30 --output "$body" --write-out '%{http_code}' \
    -H "api-token: $DISCLOUD_API_TOKEN" \
    "$DISCLOUD_API_URL/app/$DISCLOUD_APP_ID/status")" || code=000
  if [ "$code" != "200" ]; then
    echo unknown
    return
  fi
  "$PYTHON" - "$body" "$started" "$CLOCK_SKEW_SECONDS" <<'PY' 2>/dev/null || echo unknown
import json
import sys
from datetime import datetime, timezone

data = json.load(open(sys.argv[1], encoding="utf-8"))
apps = data["apps"]
app = apps[0] if isinstance(apps, list) else apps
started = datetime.fromisoformat(app["startedAt"].replace("Z", "+00:00"))
if started.tzinfo is None:
    started = started.replace(tzinfo=timezone.utc)
print("yes" if started.timestamp() >= float(sys.argv[2]) - float(sys.argv[3]) else "no")
PY
}

# Pronto = /ready com HTTP 200 e JSON com o Laya aquecido ("warm") ou desligado ("off").
# Durante o boot o proxy da Discloud serve páginas HTML de erro que chegaram a passar por
# saúde só pelo código HTTP; por isso o corpo é validado.
app_ready() {
  local body code
  body="$(mktemp)"
  code="$(curl --silent --max-time 15 --output "$body" --write-out '%{http_code}' \
    "$APP_URL/ready")" || return 1
  [ "$code" = "200" ] || return 1
  "$PYTHON" - "$body" <<'PY' 2>/dev/null
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if data.get("laya") in ("warm", "off") else 1)
PY
}

wait_ready() {
  local started body attempt restarted warned=0
  [ -f "$STARTED_FILE" ] || { echo "::error::sem registro do início do deploy"; exit 1; }
  started="$(cat "$STARTED_FILE")"
  body="$(mktemp)"
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    restarted="$(restart_state "$body" "$started")"
    if [ "$restarted" = "unknown" ] && [ "$warned" -eq 0 ]; then
      echo "::warning::Status da Discloud sem startedAt legível; confirmando só pelo /ready"
      warned=1
    fi
    if [ "$restarted" != "no" ] && app_ready; then
      echo "App pronto em $APP_URL/ready na tentativa $attempt (reiniciou depois do deploy: $restarted)"
      return 0
    fi
    echo "Tentativa $attempt/$MAX_ATTEMPTS: reiniciou=$restarted; aguardando ${POLL_INTERVAL}s"
    sleep "$POLL_INTERVAL"
  done
  echo "::error::O app não reiniciou e ficou pronto em $APP_URL/ready a tempo"
  exit 1
}

case "${1:-}" in
  commit) commit "${2:?Uso: discloud-deploy.sh commit <zip>}" ;;
  wait-ready) wait_ready ;;
  *) echo "Uso: discloud-deploy.sh commit <zip> | wait-ready" >&2; exit 2 ;;
esac
