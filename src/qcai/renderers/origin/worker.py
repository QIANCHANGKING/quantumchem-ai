"""Isolated subprocess worker for driving Origin 2024b across all 10 plot kinds."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from qcai.renderers.spec import FigureSpec


def _plot_levels(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    channels: list[dict[str, Any]] = spec.data["channels"]
    open_shell: bool = bool(spec.data["open_shell"])
    centers = [0.35, 0.75] if open_shell else [0.5]

    wks = op.new_sheet("w", "LevelsData")
    col = 0
    occ_pairs: list[tuple[int, int]] = []
    virt_pairs: list[tuple[int, int]] = []

    for ch_idx, ch in enumerate(channels):
        cx = centers[ch_idx]
        occ_x: list[float] = []
        occ_y: list[float] = []
        virt_x: list[float] = []
        virt_y: list[float] = []
        for orb in ch["orbitals"]:
            deg = max(1, int(orb["degeneracy"]))
            slot = int(orb["slot"])
            total_w = 0.24
            seg_w = total_w / deg
            x0 = cx - total_w / 2.0 + slot * seg_w + 0.008
            x1 = max(x0 + 0.02, x0 + seg_w - 0.016)
            e = float(orb["energy_ev"])
            target_x = occ_x if orb["occupied"] else virt_x
            target_y = occ_y if orb["occupied"] else virt_y
            target_x.extend([x0, x1, float("nan")])
            target_y.extend([e, e, float("nan")])

        if occ_x:
            wks.from_list(col, occ_x, f"X_occ_{ch['name']}")
            wks.from_list(col + 1, occ_y, f"Occ_{ch['name']} (eV)")
            occ_pairs.append((col, col + 1))
            col += 2
        if virt_x:
            wks.from_list(col, virt_x, f"X_virt_{ch['name']}")
            wks.from_list(col + 1, virt_y, f"Virt_{ch['name']} (eV)")
            virt_pairs.append((col, col + 1))
            col += 2

    graph = op.new_graph(template=str(template) if template else "line")
    gl = graph[0]
    for xcol, ycol in occ_pairs:
        p = gl.add_plot(wks, ycol, xcol)
        p.color = "#1f4e78"
    for xcol, ycol in virt_pairs:
        p = gl.add_plot(wks, ycol, xcol)
        p.color = "#d95f02"
    gl.rescale()
    gl.set_xlim(0.05, 1.05)
    return graph


def _plot_levels_compare(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "LevelsCompare")
    series = spec.data["series"]
    col = 0
    pairs: list[tuple[int, int]] = []
    for idx, item in enumerate(series):
        xs: list[float] = []
        ys: list[float] = []
        for e in item["occ_ev"] + item["virt_ev"]:
            xs.extend([idx - 0.25, idx + 0.25, float("nan")])
            ys.extend([float(e), float(e), float("nan")])
        wks.from_list(col, xs, f"X_{item['label']}")
        wks.from_list(col + 1, ys, str(item["label"]))
        pairs.append((col, col + 1))
        col += 2
    graph = op.new_graph(template=str(template) if template else "line")
    gl = graph[0]
    for xcol, ycol in pairs:
        gl.add_plot(wks, ycol, xcol)
    gl.rescale()
    return graph


def _plot_spin(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "SpinData")
    wks.from_list(0, spec.data["atom_labels"], "Atom")
    wks.from_list(1, spec.data["spin_values"], "Spin Population (e)")
    graph = op.new_graph(template=str(template) if template else "column")
    gl = graph[0]
    plot = gl.add_plot(wks, 1, 0, type=203)
    plot.color = "#2b6cb0"
    gl.rescale()
    return graph


def _plot_dos(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "TDOSData")
    energies: list[float] = spec.data["energies_ev"]
    tdos_alpha: list[float] = spec.data["tdos_alpha"]
    tdos_beta: list[float] | None = spec.data.get("tdos_beta")

    wks.from_list(0, energies, "Energy (eV)")
    wks.from_list(1, tdos_alpha, "TDOS alpha")
    col_idx = 2
    beta_col: int | None = None
    if tdos_beta is not None:
        wks.from_list(col_idx, tdos_beta, "TDOS beta")
        beta_col = col_idx
        col_idx += 1

    pdos_cols: list[int] = []
    for pname, pvals in spec.data.get("pdos_series", {}).items():
        if len(pvals) == len(energies):
            wks.from_list(col_idx, pvals, str(pname))
            pdos_cols.append(col_idx)
            col_idx += 1

    graph = op.new_graph(template=str(template) if template else "line")
    gl = graph[0]
    p_a = gl.add_plot(wks, 1, 0)
    p_a.color = "#1f4e78"
    if beta_col is not None:
        p_b = gl.add_plot(wks, beta_col, 0)
        p_b.color = "#c0392b"
    for pc in pdos_cols:
        gl.add_plot(wks, pc, 0)
    gl.rescale()
    return graph


def _plot_orb_comp(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "OrbCompData")
    wks.from_list(0, spec.data["orbital_labels"], "Orbital")
    col = 1
    ycols: list[int] = []
    for name, vals in spec.data["series"].items():
        wks.from_list(col, vals, str(name))
        ycols.append(col)
        col += 1
    graph = op.new_graph(template=str(template) if template else "column")
    gl = graph[0]
    for yc in ycols:
        gl.add_plot(wks, yc, 0, type=203)
    gl.rescale()
    return graph


def _plot_spin_ladder(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "SpinLadder")
    wks.from_list(0, spec.data["multiplicities"], "Multiplicity")
    wks.from_list(1, spec.data["rel_energies_ev"], "Delta E (eV)")
    graph = op.new_graph(template=str(template) if template else "line")
    gl = graph[0]
    p = gl.add_plot(wks, 1, 0)
    p.color = "#1f4e78"
    gl.rescale()
    return graph


def _plot_isomer_ranking(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "IsomerRanking")
    wks.from_list(0, spec.data["labels"], "Isomer")
    wks.from_list(1, spec.data["rel_energies_ev"], "Delta E (eV)")
    graph = op.new_graph(template=str(template) if template else "column")
    gl = graph[0]
    p = gl.add_plot(wks, 1, 0, type=203)
    p.color = "#4c72b0"
    gl.rescale()
    return graph


def _plot_size_evolution(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "SizeEvolution")
    sizes = spec.data["sizes"]
    wks.from_list(0, sizes, "Size n")
    wks.from_list(1, [v if v is not None else float("nan") for v in spec.data["eb_ev"]], "Eb (eV)")
    wks.from_list(
        2, [v if v is not None else float("nan") for v in spec.data["delta2_e_ev"]], "Delta2E (eV)"
    )
    wks.from_list(3, [v if v is not None else float("nan") for v in spec.data["gap_ev"]], "Eg (eV)")
    wks.from_list(4, [v if v is not None else float("nan") for v in spec.data["mu_b"]], "mu (muB)")

    graph = op.new_graph(template=str(template) if template else "PAN4")
    if graph is None:
        graph = op.new_graph(template="line")
    if len(graph) >= 4:
        for i in range(4):
            graph[i].add_plot(wks, i + 1, 0)
            graph[i].rescale()
    else:
        gl = graph[0]
        for i in range(1, 5):
            gl.add_plot(wks, i, 0)
        gl.rescale()
    return graph


def _plot_vde_ade(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "VDEADE")
    wks.from_list(0, spec.data["labels"], "Transition")
    wks.from_list(1, spec.data["calculated_ev"], "Calculated (eV)")
    graph = op.new_graph(template=str(template) if template else "column")
    gl = graph[0]
    gl.add_plot(wks, 1, 0, type=203)
    if any(v is not None for v in spec.data["experimental_ev"]):
        wks.from_list(
            2,
            [float(v) if v is not None else float("nan") for v in spec.data["experimental_ev"]],
            "Experimental (eV)",
        )
        gl.add_plot(wks, 2, 0, type=203)
    gl.rescale()
    return graph


def _plot_s2(op: Any, spec: FigureSpec, template: Path | None) -> Any:
    wks = op.new_sheet("w", "S2Data")
    wks.from_list(0, spec.data["labels"], "State")
    wks.from_list(1, spec.data["values"], "<S^2>")
    graph = op.new_graph(template=str(template) if template else "column")
    gl = graph[0]
    plot = gl.add_plot(wks, 1, 0, type=203)
    plot.color = "#4c72b0"
    gl.rescale()
    return graph


def run_origin_job(
    spec: FigureSpec, out_dir: Path, templates_dir: Path | None = None
) -> list[Path]:
    """Execute Origin rendering inside the current process."""
    import originpro as op

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{spec.filename_stem}.png"
    svg_path = out_dir / f"{spec.filename_stem}.svg"
    opju_path = out_dir / f"{spec.filename_stem}.opju"
    for target in (png_path, svg_path, opju_path):
        if target.exists():
            target.unlink()

    template: Path | None = None
    if templates_dir is not None:
        cand = templates_dir / f"{spec.kind}.otpu"
        if cand.exists():
            template = cand

    op.set_show(False)
    try:
        op.new()
        builders = {
            "levels": _plot_levels,
            "levels_compare": _plot_levels_compare,
            "spin": _plot_spin,
            "dos": _plot_dos,
            "orb_comp": _plot_orb_comp,
            "spin_ladder": _plot_spin_ladder,
            "isomer_ranking": _plot_isomer_ranking,
            "size_evolution": _plot_size_evolution,
            "vde_ade": _plot_vde_ade,
            "s2": _plot_s2,
        }
        builder = builders.get(spec.kind)
        if builder is None:
            raise ValueError(f"Unsupported figure kind for Origin: {spec.kind!r}")
        graph = builder(op, spec, template)
        graph.save_fig(str(png_path), type="png", width=2400)
        graph.save_fig(str(svg_path), type="svg")
        op.save(str(opju_path))
    finally:
        op.exit()

    return [png_path, svg_path, opju_path]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        raise SystemExit(
            "Usage: python -m qcai.renderers.origin.worker <spec.json> <out_dir> [templates_dir]"
        )
    spec_path = Path(argv[1])
    out_dir = Path(argv[2])
    templates_dir = Path(argv[3]) if len(argv) > 3 and argv[3] else None
    spec = FigureSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    outputs = run_origin_job(spec, out_dir, templates_dir=templates_dir)
    print(json.dumps([str(p) for p in outputs]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
