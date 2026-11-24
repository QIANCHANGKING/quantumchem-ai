"""Abstract base class for quantum chemistry program adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from qcai.core.models import CalcResult, CalcSpec, Cluster, ElectronicState


class QCProgram(ABC):
    """Interface for quantum chemistry input generation and output parsing."""

    name: str

    @abstractmethod
    def write_input(
        self,
        cluster: Cluster,
        state: ElectronicState,
        spec: CalcSpec,
        out_path: Path,
        *,
        nproc: int = 4,
        mem_gb: int = 8,
        chk_name: str | None = None,
    ) -> Path:
        """Write program input file and return its path."""

    @abstractmethod
    def parse_output(self, log_path: Path, job_id: str | None = None) -> CalcResult:
        """Parse program output file into a CalcResult."""
