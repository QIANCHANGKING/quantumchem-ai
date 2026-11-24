"""Figure renderers and shared registration."""

from qcai.interfaces import RENDERERS
from qcai.renderers.mpl import MatplotlibRenderer
from qcai.renderers.origin import OriginRenderer
from qcai.renderers.spec import FigureKind, FigureSpec, build_figure_spec

if "mpl" not in RENDERERS:
    RENDERERS.register("mpl", MatplotlibRenderer())
if "origin" not in RENDERERS:
    RENDERERS.register("origin", OriginRenderer())

__all__ = [
    "RENDERERS",
    "FigureKind",
    "FigureSpec",
    "MatplotlibRenderer",
    "OriginRenderer",
    "build_figure_spec",
]
