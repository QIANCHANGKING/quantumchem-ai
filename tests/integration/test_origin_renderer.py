"""Integration tests for Origin 2024b renderer (run with `pytest -m origin`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.renderers import RENDERERS, build_figure_spec

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "cclib"


@pytest.mark.origin
@pytest.mark.parametrize("kind", ["levels", "spin", "dos", "s2"])
def test_origin_renderer_outputs(tmp_path: Path, kind: str) -> None:
    res = parse_gaussian_log(DATA_DIR / "dvb_un_sp.log")
    spec = build_figure_spec(res, kind)  # type: ignore[arg-type]
    renderer = RENDERERS.get("origin")
    files = renderer.render(spec, tmp_path)
    assert len(files) == 3  # png, svg, opju
    for path in files:
        assert path.exists() and path.stat().st_size > 0
