from datetime import UTC, datetime

from app.store.memory import MemoryStore

INGESTED_LONG_AGO = datetime(2025, 1, 1, tzinfo=UTC)

CHARACTERS = {
    "storm": {
        "name": "Storm",
        "realName": "Ororo Munroe",
        "origin": "Mutant",
        "powers": ["Flight", "Energy"],
        "teams": ["XMen"],
        "styles": ["Leadership", "Idealist"],
        "issueAppearances": 4000,
        "imageUrl": "https://img/storm.jpg",
        "firstAppearance": "Giant-Size X-Men #1",
        "bio": "Ororo Munroe é uma mutante que controla o clima.",
        "sourceUrl": "https://comicvine.gamespot.com/storm/4005-1468/",
        "source": "Comic Vine",
        "tier": "A",
    },
    "iron-man": {
        "name": "Iron Man",
        "realName": "Tony Stark",
        "origin": "Human",
        "powers": ["TechGadgets", "Flight"],
        "teams": ["Avengers"],
        "styles": ["Science", "Leadership"],
        "issueAppearances": 7000,
        "imageUrl": "https://img/iron-man.jpg",
        "source": "Comic Vine",
        "tier": "A",
    },
    "rocket": {
        "name": "Rocket Raccoon",
        "origin": "Animal",
        "powers": ["TechGadgets"],
        "teams": ["Guardians"],
        "styles": ["Humor", "Rebel"],
        "issueAppearances": 900,
        "source": "Comic Vine",
        "tier": "B",
    },
    "jean-grey": {
        "name": "Jean Grey",
        "origin": "Mutant",
        "powers": ["Mind"],
        "teams": ["XMen"],
        "styles": ["Idealist"],
        "issueAppearances": 3500,
        "imageUrl": "https://img/jean.jpg",
        "source": "Comic Vine",
        "tier": "A",
    },
    "out-of-tier": {
        "name": "Ninguém",
        "origin": "Human",
        "tier": None,
    },
}

INITIAL_PREFERENCES = {
    "origins": ["Mutant", "Human"],
    "powers": ["Mind", "TechGadgets"],
    "teams": ["XMen"],
    "styles": ["Leadership"],
    "fame": 0.5,
}


def seed_characters(store: MemoryStore) -> None:
    for character_id, doc in CHARACTERS.items():
        store.set(f"characters/{character_id}", {**doc, "ingestedAt": INGESTED_LONG_AGO})


def seed_user(store: MemoryStore, uid: str, preferences: dict | None = None) -> None:
    store.set(
        f"users/{uid}",
        {
            "displayName": "Ana",
            "status": "active",
            "preferences": preferences or INITIAL_PREFERENCES,
        },
    )
