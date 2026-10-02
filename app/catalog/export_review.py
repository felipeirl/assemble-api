"""Exporta a fila de revisão da Superhero API para data/superhero_review.json.

Uso local (com FIREBASE_SERVICE_ACCOUNT_JSON no .env): `uv run python -m app.catalog.export_review`.
A revisão humana copia os pares confirmados para data/superhero_matches.json.
"""

import json

from app.catalog.ingest import STATE_PATH
from app.catalog.mapping import DATA_DIR
from app.config import get_settings
from app.container import build_container

REVIEW_FILE = DATA_DIR / "superhero_review.json"


def export_review() -> int:
    container = build_container(get_settings())
    queue = (container.store.get(STATE_PATH) or {}).get("superheroReview", {})
    payload = {
        "_comment": "Personagens sem par seguro na Superhero API. Confirmar o id na fonte e "
        "copiar para data/superhero_matches.json (null = sem par).",
        "pending": dict(sorted(queue.items())),
    }
    REVIEW_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return len(queue)


if __name__ == "__main__":
    print(f"{export_review()} personagens em {REVIEW_FILE}")
