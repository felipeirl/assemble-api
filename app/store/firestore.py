from typing import Any

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter

from app.store.base import DELETE_FIELD, Document, DocumentNotFoundError, Filter, Increment


class FirestoreStore:
    def __init__(self, client: firestore.Client) -> None:
        self._db = client

    def get(self, path: str) -> dict[str, Any] | None:
        snapshot = self._db.document(path).get()
        return snapshot.to_dict() if snapshot.exists else None

    def create(self, path: str, data: dict[str, Any]) -> bool:
        try:
            self._db.document(path).create(_to_firestore(data))
        except AlreadyExists:
            return False
        return True

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        self._db.document(path).set(_to_firestore(data), merge=merge)

    def update(self, path: str, data: dict[str, Any]) -> None:
        try:
            self._db.document(path).update(_to_firestore(data))
        except NotFound as exc:
            raise DocumentNotFoundError(path) from exc

    def delete(self, path: str) -> None:
        self._db.document(path).delete()

    def query(
        self,
        collection: str,
        filters: tuple[Filter, ...] = (),
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[Document]:
        query = self._build_query(collection, filters)
        if order_by is not None:
            direction = firestore.Query.DESCENDING if descending else firestore.Query.ASCENDING
            query = query.order_by(order_by, direction=direction)
        if limit is not None:
            query = query.limit(limit)
        return [(snapshot.id, snapshot.to_dict()) for snapshot in query.stream()]

    def count(self, collection: str, filters: tuple[Filter, ...] = ()) -> int:
        result = self._build_query(collection, filters).count().get()
        return int(result[0][0].value)

    def delete_tree(self, path: str) -> None:
        reference = self._db.document(path)
        self._db.recursive_delete(reference)
        reference.delete()

    def _build_query(self, collection: str, filters: tuple[Filter, ...]):
        query = self._db.collection(collection)
        for field, op, value in filters:
            query = query.where(filter=FieldFilter(field, op, value))
        return query


def _to_firestore(data: dict[str, Any]) -> dict[str, Any]:
    return {key: _convert(value) for key, value in data.items()}


def _convert(value: Any) -> Any:
    if isinstance(value, Increment):
        return firestore.Increment(value.amount)
    if value is DELETE_FIELD:
        return firestore.DELETE_FIELD
    return value
