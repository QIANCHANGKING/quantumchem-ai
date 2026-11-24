"""Abstract base class for structure generators."""

from __future__ import annotations

from abc import ABC, abstractmethod

from qcai.core.models import Cluster


class StructureGenerator(ABC):
    """Interface for initial / global cluster structure generators."""

    name: str
    priority: int = 100

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the backing generator executable/library is available."""

    @abstractmethod
    def generate(
        self,
        composition: dict[str, int],
        *,
        max_candidates: int = 20,
        charge: int = 0,
        multiplicity: int = 1,
    ) -> list[Cluster]:
        """Generate candidate Cluster geometries for the given stoichiometry."""
