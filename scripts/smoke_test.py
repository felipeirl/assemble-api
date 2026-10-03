"""Teste de fumaça contra um backend em execução, com login real do Firebase.

Cria decisões e mensagens reais para o usuário de teste. Uso (backend de pé na porta 8000):

    uv run python scripts/smoke_test.py --email teste@exemplo.com

A chave web do Firebase vem de FIREBASE_WEB_API_KEY ou é pedida; a senha é sempre pedida
no terminal e nunca é gravada.
"""

import argparse
import getpass
import os
import sys
import uuid

import httpx

SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
TIMEOUT_SECONDS = 120.0  # o match gera a fala de abertura com o modelo
MAX_ASSEMBLE_ATTEMPTS = 8
SUGGESTIONS_EXPECTED = 3


class SmokeFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def step(name: str) -> None:
    print(f"- {name} ... ", end="", flush=True)


def ok(detail: str = "") -> None:
    print(f"OK {detail}".rstrip())


def sign_in(api_key: str, email: str, password: str) -> str:
    response = httpx.post(
        SIGN_IN_URL,
        params={"key": api_key},
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=TIMEOUT_SECONDS,
    )
    check(response.status_code == 200, f"login recusado pelo Firebase ({response.status_code})")
    return response.json()["idToken"]


def run(base_url: str, api_key: str, email: str, password: str) -> None:
    http = httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS)

    step("GET /health")
    check(http.get("/health").json() == {"status": "ok"}, "resposta inesperada")
    ok()

    step("login no Firebase")
    token = sign_in(api_key, email, password)
    http.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept-Language": "pt-BR",
            "X-Timezone": "America/Sao_Paulo",
        }
    )
    ok()

    step("sem token é recusado")
    check(httpx.get(f"{base_url}/v2/deck").status_code == 401, "esperado 401")
    ok()

    step("GET /v2/deck")
    deck = http.get("/v2/deck")
    check(deck.status_code == 200, f"status {deck.status_code}: {deck.text[:200]}")
    cards = deck.json()["cards"]
    check(bool(cards), "baralho vazio: rode /jobs/ingest antes")
    check("score" not in str(cards), "o baralho não pode expor compatibilidade")
    ok(f"{len(cards)} cards")

    step("GET /v2/characters/{id} (prévia)")
    preview = http.get(f"/v2/characters/{cards[0]['characterId']}").json()
    check(preview["connected"] is False and "facts" not in preview, "prévia vazou dados")
    ok(preview["name"])

    step("POST /v2/decisions ASSEMBLE até dar match")
    match = None
    for card in cards[:MAX_ASSEMBLE_ATTEMPTS]:
        response = http.post(
            "/v2/decisions",
            json={"characterId": card["characterId"], "choice": "ASSEMBLE"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        check(response.status_code == 200, f"status {response.status_code}: {response.text[:200]}")
        if response.json()["matched"]:
            match = response.json()
            break
    check(match is not None, "nenhum match nas tentativas; reveja preferências ou o corte")
    ok(f"{match['character']['name']} (score {match['score']})")
    connection_id = match["connectionId"]

    step("POST /v2/connections/{id}/messages")
    reply = http.post(
        f"/v2/connections/{connection_id}/messages",
        json={"text": "Oi! Quem é você e o que faz?"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    check(reply.status_code == 200, f"status {reply.status_code}: {reply.text[:200]}")
    body = reply.json()
    check(body["reply"]["fictional"] is True, "resposta do personagem deve ser ficção")
    check(len(body["suggestions"]) == SUGGESTIONS_EXPECTED, "esperadas 3 sugestões")
    ok(body["reply"]["text"][:60])

    step("GET /v2/characters/{id} (perfil completo)")
    profile = http.get(f"/v2/characters/{connection_id}").json()
    check(profile["connected"] is True and "facts" in profile, "perfil incompleto")
    ok(f"fontes: {[s['name'] for s in profile['sources']]}")

    step("GET /v2/me/stats")
    stats = http.get("/v2/me/stats").json()
    check(stats["connections"] >= 1 and stats["messagesSent"] >= 1, f"estatísticas: {stats}")
    ok(str(stats))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    api_key = os.environ.get("FIREBASE_WEB_API_KEY") or getpass.getpass("Chave web do Firebase: ")
    password = getpass.getpass(f"Senha de {args.email}: ")
    try:
        run(args.base_url.rstrip("/"), api_key, args.email, password)
    except SmokeFailure as exc:
        print(f"FALHOU: {exc}")
        return 1
    except httpx.HTTPError as exc:
        print(f"FALHOU: erro de rede ({type(exc).__name__})")
        return 1
    print("\nTudo certo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
