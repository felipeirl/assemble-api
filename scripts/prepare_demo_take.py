"""Prepara um take do vídeo: reseta a conta de demonstração e fixa o baralho.

Apaga `users/{uid}` inteiro (decisões, conversas, conexões), recria o perfil sem cadastro (o
onboarding volta no próximo login) e grava `deckPin` (os personagens que abrem o baralho, na
ordem) e `forceMatch` (o Assemble neles sempre dá match). Não mexe no Firebase Auth.

Uso (na raiz do projeto, com o .env preenchido):

    uv run python scripts/prepare_demo_take.py                 # reseta e fixa o baralho
    uv run python scripts/prepare_demo_take.py --clear         # só tira deckPin e forceMatch

O terceiro personagem de `--pin` é o que recebe o match.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from firebase_admin import auth  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.firebase import firestore_client, init_firebase  # noqa: E402
from app.store.base import DELETE_FIELD  # noqa: E402
from app.store.firestore import FirestoreStore  # noqa: E402

DEFAULT_EMAIL = "sextafeira@gmail.com"
DEFAULT_PIN = ["black-widow", "spider-man", "iron-man"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--name", default="Sexta-feira")
    parser.add_argument("--pin", nargs=3, metavar="ID", default=DEFAULT_PIN)
    parser.add_argument("--clear", action="store_true", help="tira deckPin e forceMatch e sai")
    args = parser.parse_args()

    settings = get_settings()
    if settings.firebase_service_account_json is None:
        sys.exit("FIREBASE_SERVICE_ACCOUNT_JSON não configurada no .env.")
    app = init_firebase(settings.firebase_service_account_json.get_secret_value())
    store = FirestoreStore(firestore_client(app))
    user = auth.get_user_by_email(args.email, app=app)
    path = f"users/{user.uid}"

    if args.clear:
        store.set(path, {"deckPin": DELETE_FIELD, "forceMatch": DELETE_FIELD}, merge=True)
        print(f"deckPin e forceMatch removidos de {args.email}.")
        return

    for character_id in args.pin:
        found = store.get(f"characters/{character_id}")
        if found is None or found.get("tier") is None:
            sys.exit(f"Personagem '{character_id}' não existe ou não é elegível no catálogo.")

    store.delete_tree(path)
    store.set(
        path,
        {
            "displayName": args.name,
            "bio": "Conta de demonstração.",
            "avatarPreset": 0,
            "status": "active",
            "createdAt": datetime.now(UTC),
            "deckPin": args.pin,
            "forceMatch": [args.pin[2]],
        },
    )
    print(f"{args.email} resetada. Baralho: {', '.join(args.pin)}. Match garantido: {args.pin[2]}.")


if __name__ == "__main__":
    main()
