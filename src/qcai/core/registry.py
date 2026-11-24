"""Generic extension registry for QuantumChem AI (Axiom A6)."""

from __future__ import annotations


class Registry[T]:
    """Thread-safe-enough in-process registry keyed by lowercase identifier."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}

    def register(self, name: str, item: T, *, overwrite: bool = False) -> T:
        key = name.strip().lower()
        if not key:
            raise ValueError(f"{self._kind} name cannot be empty")
        if key in self._items and not overwrite:
            raise KeyError(f"{self._kind} {key!r} is already registered")
        self._items[key] = item
        return item

    def get(self, name: str) -> T:
        key = name.strip().lower()
        if key not in self._items:
            available = ", ".join(sorted(self._items)) or "<none>"
            raise KeyError(f"Unknown {self._kind} {name!r}; available: {available}")
        return self._items[key]

    def list_names(self) -> list[str]:
        return sorted(self._items)

    def __contains__(self, name: str) -> bool:
        return name.strip().lower() in self._items
