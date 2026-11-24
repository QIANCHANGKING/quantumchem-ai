"""Abstract base class for system profiles (clusters, periodic, molecules, etc.)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from qcai.core.models import Cluster, ElectronicState, ResearchRequest


class ClusterProfile(ABC):
    """Defines domain-specific validation and metadata for a chemical system class."""

    name: str

    @abstractmethod
    def validate_request(self, request: ResearchRequest) -> list[str]:
        """Return validation warning or error messages for a research request."""

    @abstractmethod
    def validate_geometry(self, cluster: Cluster) -> list[str]:
        """Return geometry sanity errors (e.g. overlapping or isolated atoms)."""

    @abstractmethod
    def default_state(self, cluster: Cluster) -> ElectronicState:
        """Return default electronic state for a cluster."""
