"""Abstract base class for 2D/3D figure renderers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qcai.renderers.spec import FigureSpec


class FigureRenderer(ABC):
    """Interface implemented by Matplotlib, Origin, py3Dmol, and VMD renderers."""

    name: str

    @abstractmethod
    def render(self, spec: FigureSpec, out_dir: Path) -> list[Path]:
        """Render the figure specification into out_dir and return generated file paths."""
