import pytest

from app.store.base import DocumentNotFoundError, Increment
from app.store.memory import MemoryStore


def test_create_is_atomic_once():
    store = MemoryStore()

    assert store.create("users/u1", {"a": 1}) is True
    assert store.create("users/u1", {"a": 2}) is False
    assert store.get("users/u1") == {"a": 1}


def test_update_missing_document_raises():
    with pytest.raises(DocumentNotFoundError):
        MemoryStore().update("users/u1", {"a": 1})


def test_increment():
    store = MemoryStore()
    store.set("users/u1/matches/storm", {"userMessageCount": 0})

    store.update("users/u1/matches/storm", {"userMessageCount": Increment(2)})

    assert store.get("users/u1/matches/storm")["userMessageCount"] == 2


def test_query_only_direct_children_with_filters_order_and_limit():
    store = MemoryStore()
    store.set("users/u1/decisions/a", {"choice": "PASS", "n": 2})
    store.set("users/u1/decisions/b", {"choice": "PASS", "n": 1})
    store.set("users/u1/decisions/c", {"choice": "ASSEMBLE", "n": 3})
    store.set("users/u1/decisions/a/sub/x", {"choice": "PASS", "n": 0})

    result = store.query(
        "users/u1/decisions", filters=(("choice", "==", "PASS"),), order_by="n", limit=1
    )

    assert result == [("b", {"choice": "PASS", "n": 1})]


def test_delete_tree_removes_subcollections_only_under_path():
    store = MemoryStore()
    store.set("users/u1", {"x": 1})
    store.set("users/u1/matches/storm", {"x": 1})
    store.set("users/u10", {"x": 1})

    store.delete_tree("users/u1")

    assert store.get("users/u1") is None
    assert store.get("users/u1/matches/storm") is None
    assert store.get("users/u10") == {"x": 1}
