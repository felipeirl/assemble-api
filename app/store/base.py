from dataclasses import dataclass
from typing import Any, Protocol

Filter = tuple[str, str, Any]
Document = tuple[str, dict[str, Any]]


class DocumentNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class Increment:
    """Incremento atômico de um campo numérico em `update`."""

    amount: int


class _DeleteField:
    """Remove o campo em `set(merge=True)` ou `update`. Singleton, inclusive em deepcopy."""

    def __copy__(self) -> "_DeleteField":
        return self

    def __deepcopy__(self, memo: dict) -> "_DeleteField":
        return self


DELETE_FIELD = _DeleteField()


class DocumentStore(Protocol):
    """Acesso mínimo a documentos por caminho (ex.: `users/{uid}/decisions/{id}`)."""

    def get(self, path: str) -> dict[str, Any] | None: ...

    def create(self, path: str, data: dict[str, Any]) -> bool:
        """Cria o documento; devolve False se ele já existir (operação atômica)."""
        ...

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None: ...

    def update(self, path: str, data: dict[str, Any]) -> None:
        """Atualiza campos; levanta DocumentNotFoundError se o documento não existir."""
        ...

    def delete(self, path: str) -> None: ...

    def query(
        self,
        collection: str,
        filters: tuple[Filter, ...] = (),
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[Document]: ...

    def count(self, collection: str, filters: tuple[Filter, ...] = ()) -> int: ...

    def delete_tree(self, path: str) -> None:
        """Apaga o documento e todas as subcoleções."""
        ...
