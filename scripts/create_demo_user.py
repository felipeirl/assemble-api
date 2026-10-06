"""Cria (ou atualiza) uma conta de demonstração com o e-mail já confirmado.

A conta nasce SEM cadastro: ao tocar em "Entrar", o app abre direto o onboarding (passos de
preferências, rodada "este ou aquele" e revelação), para você mostrar a escolha ao vivo. Com
`--skip-onboarding`, o cadastro já vem concluído, com preferências vazias.

Uso (na raiz do projeto, com o .env preenchido):

    uv run python scripts/create_demo_user.py EMAIL SENHA [--name "Nome"] [--skip-onboarding]

Rodar de novo com o mesmo e-mail redefine a senha e volta o perfil ao estado inicial (decisões e
conversas ficam; apague-as se quiser recomeçar de verdade).
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

AI_CONSENT_VERSION = "v1"
# Vazias = "Qualquer" em todas as categorias; a fama no meio.
EMPTY_PREFERENCES = {"origins": [], "powers": [], "teams": [], "styles": [], "fame": 0.5}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("--name", default="Sexta-feira")
    parser.add_argument(
        "--skip-onboarding",
        action="store_true",
        help="deixa o cadastro concluído, com preferências vazias",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.firebase_service_account_json is None:
        sys.exit("FIREBASE_SERVICE_ACCOUNT_JSON não configurada no .env.")
    app = init_firebase(settings.firebase_service_account_json.get_secret_value())

    try:
        user = auth.get_user_by_email(args.email, app=app)
        user = auth.update_user(
            user.uid,
            password=args.password,
            email_verified=True,
            display_name=args.name,
            disabled=False,
            app=app,
        )
        print(f"Conta existente atualizada: {user.uid}")
    except auth.UserNotFoundError:
        user = auth.create_user(
            email=args.email,
            password=args.password,
            email_verified=True,
            display_name=args.name,
            app=app,
        )
        print(f"Conta criada: {user.uid}")

    now = datetime.now(UTC)
    profile = {
        "displayName": args.name,
        "bio": "Conta de demonstração.",
        "avatarPreset": 0,
        "status": "active",
        "createdAt": now,
    }
    if args.skip_onboarding:
        profile |= {
            "onboardingCompletedAt": now,
            "preferences": EMPTY_PREFERENCES,
            "aiConsent": {"acceptedAt": now, "version": AI_CONSENT_VERSION},
        }
    else:
        # Ao rodar de novo, o cadastro volta ao começo: tira o que um cadastro anterior gravou.
        profile |= {
            "onboardingCompletedAt": DELETE_FIELD,
            "preferences": DELETE_FIELD,
            "aiConsent": DELETE_FIELD,
        }
    store = FirestoreStore(firestore_client(app))
    store.set(f"users/{user.uid}", profile, merge=True)
    done = (
        "cadastro concluído, preferências vazias"
        if args.skip_onboarding
        else "onboarding no primeiro login"
    )
    print(f"Perfil pronto: {args.email} (e-mail confirmado, {done}).")


if __name__ == "__main__":
    main()
