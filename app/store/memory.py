import copy
import operator
import threading
from typing import Any

from app.store.base import DELETE_FIELD, Document, DocumentNotFoundError, Filter, Increment

_OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "in": lambda value, options: value in options,
    "array_contains": lambda value, item: isinstance(value, list) and item in value,
}


class MemoryStore:
    """Implementação em memória do DocumentStore, para testes e execução local."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._docs.get(path)
            return copy.deepcopy(doc) if doc is not None else None

    def create(self, path: str, data: dict[str, Any]) -> bool:
        with self._lock:
            if path in self._docs:
                return False
            self._docs[path] = _resolve(copy.deepcopy(data), {})
            return True

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        with self._lock:
            current = self._docs.get(path, {}) if merge else {}
            base = copy.deepcopy(current)
            _merge_into(base, data)
            self._docs[path] = base

    def update(self, path: str, data: dict[str, Any]) -> None:
        with self._lock:
            if path not in self._docs:
                raise DocumentNotFoundError(path)
            _merge_into(self._docs[path], data)

    def delete(self, path: str) -> None:
        with self._lock:
            self._docs.pop(path, None)

    def query(
        self,
        collection: str,
        filters: tuple[Filter, ...] = (),
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[Document]:
        with self._lock:
            results = [
                (path.rsplit("/", 1)[1], copy.deepcopy(doc))
                for path, doc in self._docs.items()
                if _parent(path) == collection and _matches(doc, filters)
            ]
        if order_by is not None:
            results = [r for r in results if order_by in r[1]]
            results.sort(key=lambda r: r[1][order_by], reverse=descending)
        if limit is not None:
            results = results[:limit]
        return results

    def count(self, collection: str, filters: tuple[Filter, ...] = ()) -> int:
        return len(self.query(collection, filters))

    def delete_tree(self, path: str) -> None:
        with self._lock:
            prefix = path + "/"
            for key in [k for k in self._docs if k == path or k.startswith(prefix)]:
                del self._docs[key]


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0]


def _apply(current: Any, value: Any) -> Any:
    if isinstance(value, Increment):
        return (current or 0) + value.amount
    return value


def _merge_into(doc: dict[str, Any], data: dict[str, Any]) -> None:
    for key, value in data.items():
        if value is DELETE_FIELD:
            doc.pop(key, None)
        else:
            doc[key] = _apply(doc.get(key), copy.deepcopy(value))


def _resolve(data: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _apply(current.get(key), value)
        for key, value in data.items()
        if value is not DELETE_FIELD
    }


def _matches(doc: dict[str, Any], filters: tuple[Filter, ...]) -> bool:
    for field, op, expected in filters:
        if field not in doc:
            return False
        if not _OPERATORS[op](doc[field], expected):
            return False
    return True
