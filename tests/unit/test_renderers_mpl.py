"""Unit tests for FigureSpec builders, MatplotlibRenderer, and P1 CLI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from qcai.cli import app
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.renderers import RENDERERS, build_figure_spec

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "cclib"


def test_levels_closed_vs_open_shell_spec_and_mpl(tmp_path: Path) -> None:
    closed_res = parse_gaussian_log(DATA_DIR / "dvb_sp.out")
    open_res = parse_gaussian_log(DATA_DIR / "dvb_un_sp.log")

    cs_spec = build_figure_spec(closed_res, "levels")
    os_spec = build_figure_spec(open_res, "levels")
    assert cs_spec.data["open_shell"] is False
    assert len(cs_spec.data["channels"]) == 1
    assert os_spec.data["open_shell"] is True
    assert len(os_spec.data["channels"]) == 2

    renderer = RENDERERS.get("mpl")
    for spec in (cs_spec, os_spec):
        files = renderer.render(spec, tmp_path)
        assert len(files) == 2
        for f in files:
            assert f.exists() and f.stat().st_size > 1000


def test_spin_dos_s2_mpl_rendering(tmp_path: Path) -> None:
    open_res = parse_gaussian_log(DATA_DIR / "dvb_un_sp.log")
    renderer = RENDERERS.get("mpl")

    dos_spec = build_figure_spec(open_res, "dos")
    assert dos_spec.data["open_shell"] is True
    assert all(v <= 0.0 for v in dos_spec.data["tdos_beta"])

    for kind in ("spin", "dos", "s2"):
        spec = build_figure_spec(open_res, kind)  # type: ignore[arg-type]
        files = renderer.render(spec, tmp_path)
        assert len(files) == 2
        for f in files:
            assert f.exists() and f.stat().st_size > 1000


def test_cli_parse_and_plot(tmp_path: Path) -> None:
    runner = CliRunner()
    log = DATA_DIR / "dvb_un_sp.log"
    json_out = tmp_path / "parsed.json"

    r_parse = runner.invoke(app, ["parse", str(log), "--json-out", str(json_out)])
    assert r_parse.exit_code == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["state"]["multiplicity"] == 2
    assert payload["s2_after"] == 0.7504

    for kind in ("levels", "spin", "dos", "s2"):
        r_plot = runner.invoke(
            app,
            ["plot", str(log), "--kind", kind, "--renderer", "mpl", "--out-dir", str(tmp_path)],
        )
        assert r_plot.exit_code == 0
        assert (tmp_path / f"dvb_un_sp_{kind}.png").exists()
        assert (tmp_path / f"dvb_un_sp_{kind}.svg").exists()
