from datetime import UTC, datetime, timedelta

from app.domain.enums import Origin
from app.repositories import (
    AccessLogRepository,
    CharacterRepository,
    DecisionRepository,
    MatchRepository,
    MessageRepository,
    UserRepository,
)
from app.store.base import DELETE_FIELD
from app.store.memory import MemoryStore

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_preferences_default_to_any_when_missing():
    users = UserRepository(MemoryStore())

    prefs = users.preferences("u1")

    assert prefs.origins == [] and prefs.fame == 0.5


def test_preferences_are_read_from_user_document():
    store = MemoryStore()
    store.set("users/u1", {"preferences": {"origins": ["Mutant"], "fame": 0.2}})

    prefs = UserRepository(store).preferences("u1")

    assert prefs.origins == [Origin.Mutant]
    assert prefs.fame == 0.2


def test_deactivate_and_reactivate():
    store = MemoryStore()
    users = UserRepository(store)
    store.set("users/u1", {"displayName": "Ana"})

    users.deactivate("u1", NOW)
    assert users.deactivated_before(NOW + timedelta(days=31)) == ["u1"]

    users.reactivate("u1")
    user = users.get("u1")
    assert user["status"] == "active"
    assert "deactivatedAt" not in user
    assert user["displayName"] == "Ana"
    assert users.deactivated_before(NOW + timedelta(days=31)) == []


def test_deactivated_before_respects_cutoff():
    users = UserRepository(MemoryStore())
    users.deactivate("u1", NOW)

    assert users.deactivated_before(NOW) == []


def test_decision_is_written_once_per_pair():
    decisions = DecisionRepository(MemoryStore())

    assert decisions.create("u1", "storm", {"choice": "PASS"}) is True
    assert decisions.create("u1", "storm", {"choice": "ASSEMBLE"}) is False
    assert decisions.get("u1", "storm") == {"choice": "PASS"}
    assert decisions.decided_ids("u1") == {"storm"}


def test_recent_messages_are_oldest_first_and_limited():
    messages = MessageRepository(MemoryStore())
    for minute in range(5):
        messages.add("u1", "storm", f"m{minute}", {"createdAt": NOW + timedelta(minutes=minute)})

    recent = messages.recent("u1", "storm", limit=3)

    assert [message_id for message_id, _ in recent] == ["m2", "m3", "m4"]


def test_hidden_matches_before_cutoff_and_tree_delete():
    store = MemoryStore()
    matches = MatchRepository(store)
    matches.create("u1", "storm", {"hidden": True, "hiddenAt": NOW - timedelta(days=31)})
    matches.create("u1", "rocket", {"hidden": True, "hiddenAt": NOW})
    store.set("users/u1/matches/storm/messages/m1", {"text": "oi"})

    old = matches.hidden_before("u1", NOW - timedelta(days=30))
    assert [cid for cid, _ in old] == ["storm"]

    matches.delete_with_messages("u1", "storm")
    assert store.get("users/u1/matches/storm") is None
    assert store.get("users/u1/matches/storm/messages/m1") is None
    assert matches.get("u1", "rocket") is not None


def test_eligible_characters_are_tier_a_or_b():
    characters = CharacterRepository(MemoryStore())
    characters.upsert("storm", {"tier": "A"})
    characters.upsert("rocket", {"tier": "B"})
    characters.upsert("nobody", {"tier": None})

    assert {cid for cid, _ in characters.eligible()} == {"storm", "rocket"}


def test_expired_access_logs_are_deleted():
    store = MemoryStore()
    store.set("accessLogs/old", {"expiresAt": NOW - timedelta(seconds=1)})
    store.set("accessLogs/new", {"expiresAt": NOW + timedelta(days=1)})

    deleted = AccessLogRepository(store).delete_expired(NOW)

    assert deleted == 1
    assert store.get("accessLogs/old") is None
    assert store.get("accessLogs/new") is not None


def test_delete_field_on_create_is_ignored():
    store = MemoryStore()

    store.create("users/u1", {"a": 1, "b": DELETE_FIELD})

    assert store.get("users/u1") == {"a": 1}
