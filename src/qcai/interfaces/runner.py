"""Abstract base class for remote or mock job runners."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class JobHandle:
    """Handle identifying a submitted job."""

    job_id: str
    pid: str | None
    remote_dir: Path


@dataclass(frozen=True)
class JobStatus:
    """Observed status of a submitted job."""

    job_id: str
    state: Literal["queued", "running", "done", "failed", "cancelled", "unknown"]
    fixes: list[str]
    message: str | None = None


class JobRunner(ABC):
    """Interface for submitting, polling, and cancelling quantum chemistry jobs."""

    name: str

    @abstractmethod
    def submit(
        self,
        job_id: str,
        local_dir: Path,
        remote_dir: Path,
        command: str,
    ) -> JobHandle:
        """Stage input files and launch a job."""

    @abstractmethod
    def poll(self, handle: JobHandle) -> JobStatus:
        """Poll current execution status for a job handle."""

    @abstractmethod
    def cancel(self, handle: JobHandle) -> bool:
        """Cancel a running job and return True if cancellation succeeded."""
