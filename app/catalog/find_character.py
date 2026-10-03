"""Procura personagens na Comic Vine para descobrir o id de um nome do tier A.

Uso local (com COMICVINE_API_KEY no .env):

    uv run python -m app.catalog.find_character "Maria Hill" "Falcon"

Imprime id, nome, editora e aparições dos 10 melhores resultados de cada busca (nenhum segredo).
Copie o id certo para "comicVineIds" em data/tier_a.json: {"Falcon": 1234}.
"""

import sys

import httpx

from app.catalog.comicvine import ComicVineClient
from app.config import get_settings

REQUEST_INTERVAL_SECONDS = 1.0
MAX_REQUESTS = 30


def main(names: list[str]) -> int:
    key = get_settings().comicvine_api_key
    if key is None:
        print("COMICVINE_API_KEY não está no .env.")
        return 1
    with httpx.Client(timeout=30.0, follow_redirects=True) as http:
        client = ComicVineClient(
            http, key.get_secret_value(), MAX_REQUESTS, REQUEST_INTERVAL_SECONDS
        )
        for name in names:
            print(f"\n== {name}")
            for item in client.search_characters(name):
                publisher = (item.get("publisher") or {}).get("name", "?")
                print(
                    f"  id={item['id']:<8} {item.get('name', '?'):<40} {publisher:<20} "
                    f"{item.get('count_of_issue_appearances') or 0} aparições"
                )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python -m app.catalog.find_character "Nome" ["Outro nome" ...]')
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
