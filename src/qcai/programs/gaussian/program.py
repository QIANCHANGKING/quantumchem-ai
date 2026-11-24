"""Gaussian 16 QCProgram adapter registered in QCPROGRAMS."""

from __future__ import annotations

from pathlib import Path

from qcai.core.models import CalcResult, CalcSpec, Cluster, ElectronicState
from qcai.interfaces import QCPROGRAMS, QCProgram
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.programs.gaussian.writer import write_gaussian_input


class GaussianProgram(QCProgram):
    """Gaussian 16 implementation of QCProgram."""

    name = "gaussian"

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
        return write_gaussian_input(
            cluster,
            state,
            spec,
            out_path,
            nproc=nproc,
            mem_gb=mem_gb,
            chk_name=chk_name,
        )

    def parse_output(self, log_path: Path, job_id: str | None = None) -> CalcResult:
        return parse_gaussian_log(log_path, job_id=job_id)


if "gaussian" not in QCPROGRAMS:
    QCPROGRAMS.register("gaussian", GaussianProgram())
