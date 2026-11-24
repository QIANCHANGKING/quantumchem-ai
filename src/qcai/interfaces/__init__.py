"""Extension interfaces and shared registries."""

from qcai.core.registry import Registry
from qcai.interfaces.generator import StructureGenerator
from qcai.interfaces.llm import LLMProvider
from qcai.interfaces.profile import ClusterProfile
from qcai.interfaces.qcprogram import QCProgram
from qcai.interfaces.renderer import FigureRenderer
from qcai.interfaces.runner import JobHandle, JobRunner, JobStatus

PROFILES: Registry[ClusterProfile] = Registry("profile")
GENERATORS: Registry[StructureGenerator] = Registry("generator")
RENDERERS: Registry[FigureRenderer] = Registry("renderer")
RUNNERS: Registry[JobRunner] = Registry("runner")
QCPROGRAMS: Registry[QCProgram] = Registry("qcprogram")
LLMS: Registry[LLMProvider] = Registry("llm")

__all__ = [
    "ClusterProfile",
    "FigureRenderer",
    "GENERATORS",
    "JobHandle",
    "JobRunner",
    "JobStatus",
    "LLMS",
    "LLMProvider",
    "PROFILES",
    "QCPROGRAMS",
    "QCProgram",
    "RENDERERS",
    "RUNNERS",
    "StructureGenerator",
]
