"""Renderer-agnostic FigureSpec and builders for all 10 P1/P6 visualizations."""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from qcai.core.models import CalcResult, OrbitalComposition, PDOSData
from qcai.core.physics import (
    HA_TO_EV,
    homo_lumo_gap_hartree,
    ideal_s_squared,
    is_spin_contaminated,
    total_magnetic_moment_mu_b,
)

if TYPE_CHECKING:
    from qcai.analysis.summary import ClusterSummary, ProjectSummary

FigureKind = Literal[
    "levels",
    "levels_compare",
    "spin",
    "dos",
    "orb_comp",
    "spin_ladder",
    "isomer_ranking",
    "size_evolution",
    "vde_ade",
    "s2",
]


class FigureSpec(BaseModel):
    """Tool-agnostic specification consumed by Matplotlib and Origin renderers."""

    kind: FigureKind
    title: str
    subtitle: str = ""
    x_label: str = ""
    y_label: str = ""
    filename_stem: str = "figure"
    data: dict[str, Any] = Field(default_factory=dict)
    annotations: list[dict[str, Any]] = Field(default_factory=list)


def _group_degenerate(energies_ev: list[float], tol_ev: float) -> list[tuple[int, float, int, int]]:
    if not energies_ev:
        return []
    groups: list[list[tuple[int, float]]] = []
    for idx, energy in enumerate(energies_ev):
        if groups and abs(energy - groups[-1][-1][1]) <= tol_ev:
            groups[-1].append((idx, energy))
        else:
            groups.append([(idx, energy)])
    items: list[tuple[int, float, int, int]] = []
    for grp in groups:
        size = len(grp)
        for slot, (idx, energy) in enumerate(grp):
            items.append((idx, energy, slot, size))
    return items


def _build_levels_spec(
    result: CalcResult,
    *,
    degen_tol_ev: float = 0.05,
    max_occ: int = 10,
    max_virt: int = 8,
) -> FigureSpec:
    if not result.mo_energies_hartree or not result.homo_indices:
        raise ValueError(f"Job {result.job_id!r} has no MO energy data for levels plot")

    open_shell = len(result.mo_energies_hartree) == 2
    channel_names = ["alpha", "beta"] if open_shell else ["restricted"]
    channels: list[dict[str, Any]] = []

    for ch_idx, ch_name in enumerate(channel_names):
        if ch_idx >= len(result.mo_energies_hartree) or ch_idx >= len(result.homo_indices):
            continue
        homo_idx = result.homo_indices[ch_idx]
        all_ev = [e * HA_TO_EV for e in result.mo_energies_hartree[ch_idx]]
        start = max(0, homo_idx - max_occ + 1)
        end = min(len(all_ev), homo_idx + 1 + max_virt)
        sliced = all_ev[start:end]
        grouped = _group_degenerate(sliced, degen_tol_ev)
        orbitals = [
            {
                "mo_index": start + rel_idx,
                "energy_ev": energy_ev,
                "occupied": (start + rel_idx) <= homo_idx,
                "slot": slot,
                "degeneracy": deg,
                "is_homo": (start + rel_idx) == homo_idx,
                "is_lumo": (start + rel_idx) == (homo_idx + 1),
            }
            for rel_idx, energy_ev, slot, deg in grouped
        ]
        homo_ev = all_ev[homo_idx] if 0 <= homo_idx < len(all_ev) else None
        lumo_ev = all_ev[homo_idx + 1] if (homo_idx + 1) < len(all_ev) else None
        channels.append(
            {
                "name": ch_name,
                "homo_index": homo_idx,
                "homo_ev": homo_ev,
                "lumo_ev": lumo_ev,
                "gap_ev": (lumo_ev - homo_ev)
                if (homo_ev is not None and lumo_ev is not None)
                else None,
                "orbitals": orbitals,
            }
        )

    gap_ha = homo_lumo_gap_hartree(result.mo_energies_hartree, result.homo_indices)
    gap_ev = gap_ha * HA_TO_EV if gap_ha is not None else None
    subtitle = f"M={result.state.multiplicity}, q={result.state.charge}, " + (
        f"Eg={gap_ev:.3f} eV" if gap_ev is not None else "Eg=N/A"
    )

    return FigureSpec(
        kind="levels",
        title=f"{result.job_id} 分子轨道能级图",
        subtitle=subtitle,
        x_label="自旋通道" if open_shell else "分子轨道",
        y_label="能量 (eV)",
        filename_stem=f"{result.job_id}_levels",
        data={
            "open_shell": open_shell,
            "channels": channels,
            "overall_gap_ev": gap_ev,
        },
    )


def build_levels_compare_spec(
    results: list[CalcResult],
    *,
    title: str = "分子轨道能级对比图",
    filename_stem: str = "levels_compare",
) -> FigureSpec:
    """Compare frontier orbital levels across multiple clusters (e.g. pure vs doped)."""
    series: list[dict[str, Any]] = []
    for res in results:
        if not res.mo_energies_hartree or not res.homo_indices:
            continue
        ch = res.mo_energies_hartree[0]
        h_idx = res.homo_indices[0]
        start = max(0, h_idx - 5)
        end = min(len(ch), h_idx + 5)
        occ_ev = [ch[i] * HA_TO_EV for i in range(start, min(h_idx + 1, end))]
        virt_ev = [ch[i] * HA_TO_EV for i in range(h_idx + 1, end)]
        gap_ha = homo_lumo_gap_hartree(res.mo_energies_hartree, res.homo_indices)
        series.append(
            {
                "label": res.job_id,
                "occ_ev": occ_ev,
                "virt_ev": virt_ev,
                "homo_ev": ch[h_idx] * HA_TO_EV if 0 <= h_idx < len(ch) else None,
                "lumo_ev": ch[h_idx + 1] * HA_TO_EV if (h_idx + 1) < len(ch) else None,
                "gap_ev": gap_ha * HA_TO_EV if gap_ha is not None else None,
            }
        )
    if not series:
        raise ValueError("No MO energy data found in provided results for comparison")
    return FigureSpec(
        kind="levels_compare",
        title=title,
        subtitle=f"对比体系数：{len(series)}",
        x_label="体系",
        y_label="轨道能量 (eV)",
        filename_stem=filename_stem,
        data={"series": series},
    )


def _select_population_key(pops: dict[str, list[float]]) -> str:
    for preferred in ("hirshfeld", "adch", "mulliken"):
        if preferred in pops and pops[preferred]:
            return preferred
    for key, vals in pops.items():
        if vals:
            return key
    raise ValueError("No non-empty population data available")


def _build_spin_spec(result: CalcResult) -> FigureSpec:
    if not result.spins:
        raise ValueError(f"Job {result.job_id!r} has no atomic spin population data")

    method = _select_population_key(result.spins)
    values = result.spins[method]
    symbols = (
        result.final_geometry.symbols
        if result.final_geometry is not None
        else [f"X{i + 1}" for i in range(len(values))]
    )
    counts = Counter(symbols)
    min_count = min(counts.values()) if counts else 0
    is_hetero = len(counts) > 1
    labels = [f"{i + 1}{sym}" for i, sym in enumerate(symbols)]
    highlighted = [(counts[sym] == min_count and is_hetero) for sym in symbols]
    mu_b = total_magnetic_moment_mu_b(result.state.multiplicity)

    return FigureSpec(
        kind="spin",
        title=f"{result.job_id} 原子自旋布居 ({method})",
        subtitle=f"M={result.state.multiplicity}, 总磁矩 μ = {mu_b:.2f} μB",
        x_label="原子位点",
        y_label="自旋布居 (e)",
        filename_stem=f"{result.job_id}_spin",
        data={
            "method": method,
            "atom_labels": labels,
            "symbols": symbols,
            "spin_values": values,
            "highlighted": highlighted,
            "total_spin": sum(values),
            "magnetic_moment_mu_b": mu_b,
        },
    )


def _gaussian_broaden(energies_ev: np.ndarray, grid_ev: np.ndarray, fwhm_ev: float) -> np.ndarray:
    if energies_ev.size == 0:
        return np.zeros_like(grid_ev)
    sigma = fwhm_ev / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    diff = grid_ev[:, None] - energies_ev[None, :]
    norm = 1.0 / (sigma * math.sqrt(2.0 * math.pi))
    return np.sum(norm * np.exp(-0.5 * (diff / sigma) ** 2), axis=1)


def _build_dos_spec(
    result: CalcResult,
    *,
    fwhm_ev: float = 0.30,
    n_points: int = 600,
    pad_ev: float = 2.0,
) -> FigureSpec:
    if result.pdos is not None:
        return build_pdos_spec(result.job_id, result.pdos)

    if not result.mo_energies_hartree:
        raise ValueError(f"Job {result.job_id!r} has no MO energy data for TDOS plot")

    open_shell = len(result.mo_energies_hartree) == 2
    alpha_ev = np.array(result.mo_energies_hartree[0], dtype=float) * HA_TO_EV
    all_vals = [alpha_ev]
    beta_ev = np.array([], dtype=float)
    if open_shell:
        beta_ev = np.array(result.mo_energies_hartree[1], dtype=float) * HA_TO_EV
        all_vals.append(beta_ev)

    combined = np.concatenate(all_vals)
    homo_alpha_ev = (
        float(alpha_ev[result.homo_indices[0]])
        if result.homo_indices and 0 <= result.homo_indices[0] < len(alpha_ev)
        else float(np.median(combined))
    )
    e_min = max(float(np.min(combined)) - pad_ev, homo_alpha_ev - 20.0)
    e_max = min(float(np.max(combined)) + pad_ev, homo_alpha_ev + 12.0)
    grid = np.linspace(e_min, e_max, n_points)

    tdos_alpha = _gaussian_broaden(alpha_ev, grid, fwhm_ev)
    tdos_beta = (-_gaussian_broaden(beta_ev, grid, fwhm_ev)).tolist() if open_shell else None

    return FigureSpec(
        kind="dos",
        title=f"{result.job_id} 总态密度 (TDOS)",
        subtitle=f"FWHM={fwhm_ev:.2f} eV, {'开壳层 α/β' if open_shell else '闭壳层'}",
        x_label="轨道能量 (eV)",
        y_label="态密度 (states / eV)",
        filename_stem=f"{result.job_id}_dos",
        data={
            "open_shell": open_shell,
            "energies_ev": grid.tolist(),
            "tdos_alpha": tdos_alpha.tolist(),
            "tdos_beta": tdos_beta,
            "pdos_series": {},
            "sticks_alpha_ev": alpha_ev[(alpha_ev >= e_min) & (alpha_ev <= e_max)].tolist(),
            "sticks_beta_ev": (
                beta_ev[(beta_ev >= e_min) & (beta_ev <= e_max)].tolist() if open_shell else []
            ),
            "homo_alpha_ev": homo_alpha_ev,
            "homo_beta_ev": (
                float(beta_ev[result.homo_indices[1]])
                if open_shell
                and len(result.homo_indices) > 1
                and result.homo_indices[1] < len(beta_ev)
                else None
            ),
        },
    )


def build_pdos_spec(
    label: str,
    pdos: PDOSData,
    *,
    homo_ev: float | None = None,
) -> FigureSpec:
    """Build FigureSpec from Multiwfn PDOSData (TDOS + elemental/s/p/d PDOS)."""
    open_shell = pdos.tdos_beta is not None
    return FigureSpec(
        kind="dos",
        title=f"{label} TDOS / PDOS",
        subtitle="Multiwfn PDOS（按元素与角动量分解）",
        x_label="能量 (eV)",
        y_label="态密度 (states / eV)",
        filename_stem=f"{label}_pdos",
        data={
            "open_shell": open_shell,
            "energies_ev": pdos.energies_ev,
            "tdos_alpha": pdos.tdos_alpha,
            "tdos_beta": pdos.tdos_beta,
            "pdos_series": pdos.pdos_series,
            "sticks_alpha_ev": [],
            "sticks_beta_ev": [],
            "homo_alpha_ev": homo_ev,
            "homo_beta_ev": None,
        },
    )


def build_orb_comp_spec(
    label: str,
    compositions: list[OrbitalComposition],
) -> FigureSpec:
    """Build stacked-bar orbital composition FigureSpec from Multiwfn Menu 8 output."""
    if not compositions:
        raise ValueError("No OrbitalComposition entries provided")
    orb_labels = [f"MO {c.mo_index} ({c.spin[0]})" for c in compositions]
    shell_keys = ["shell_s", "shell_p", "shell_d", "shell_f"]
    series = {
        k.replace("shell_", "").upper(): [float(c.contributions.get(k, 0.0)) for c in compositions]
        for k in shell_keys
    }
    return FigureSpec(
        kind="orb_comp",
        title=f"{label} 前线轨道角动量成分",
        subtitle="Multiwfn 轨道成分分析 (%)",
        x_label="分子轨道",
        y_label="成分占比 (%)",
        filename_stem=f"{label}_orb_comp",
        data={"orbital_labels": orb_labels, "series": series},
    )


def build_spin_ladder_spec(summary: ClusterSummary) -> FigureSpec:
    """Build spin-state energy ladder FigureSpec from ClusterSummary."""
    if not summary.spin_ladder:
        raise ValueError(f"Cluster {summary.cluster_label!r} has no spin ladder data")
    return FigureSpec(
        kind="spin_ladder",
        title=f"{summary.cluster_label} 自旋态能量阶梯",
        subtitle=f"基态 M={summary.ground_state_multiplicity}",
        x_label="自旋多重度 M = 2S + 1",
        y_label="相对能量 ΔE (eV)",
        filename_stem=f"{summary.cluster_label}_spin_ladder",
        data={
            "multiplicities": [int(m) for m, _ in summary.spin_ladder],
            "rel_energies_ev": [float(e) for _, e in summary.spin_ladder],
        },
    )


def build_isomer_ranking_spec(summary: ClusterSummary, *, max_items: int = 10) -> FigureSpec:
    """Build isomer relative-energy ranking FigureSpec from ClusterSummary."""
    entries = summary.isomers[:max_items]
    if not entries:
        raise ValueError(f"Cluster {summary.cluster_label!r} has no isomer entries")
    return FigureSpec(
        kind="isomer_ranking",
        title=f"{summary.cluster_label} 异构体能量排序",
        subtitle=f"共 {len(summary.isomers)} 个已收敛构型/自旋态",
        x_label="候选异构体",
        y_label="相对能量 ΔE (eV)",
        filename_stem=f"{summary.cluster_label}_isomers",
        data={
            "labels": [f"{e.label} (M={e.multiplicity})" for e in entries],
            "rel_energies_ev": [float(e.rel_energy_ev) for e in entries],
        },
    )


def build_size_evolution_spec(project_summary: ProjectSummary) -> FigureSpec:
    """Build 4-panel size evolution FigureSpec (Eb, Delta2E, Eg, mu)."""
    pts = project_summary.size_evolution
    if not pts:
        raise ValueError("ProjectSummary has no size evolution points")
    return FigureSpec(
        kind="size_evolution",
        title=f"{project_summary.project_id} 尺寸演化性质",
        subtitle="平均结合能 / 二阶能量差分 / 能隙 / 总磁矩",
        x_label="团簇尺寸 n",
        y_label="性质指标",
        filename_stem=f"{project_summary.project_id}_size_evolution",
        data={
            "sizes": [p.size_n for p in pts],
            "eb_ev": [p.binding_energy_ev_per_atom for p in pts],
            "delta2_e_ev": [p.delta2_e_ev for p in pts],
            "gap_ev": [p.homo_lumo_gap_ev for p in pts],
            "mu_b": [p.magnetic_moment_mu_b for p in pts],
        },
    )


def build_vde_ade_spec(
    summary: ClusterSummary,
    experimental: dict[str, float] | None = None,
) -> FigureSpec:
    """Build calculated vs experimental VDE/ADE comparison FigureSpec."""
    labels: list[str] = []
    calc_vals: list[float] = []
    exp_vals: list[float | None] = []
    exp_map = experimental or {}
    if summary.vde_ev is not None:
        labels.append("VDE")
        calc_vals.append(summary.vde_ev)
        exp_vals.append(exp_map.get("VDE") or exp_map.get("vde"))
    if summary.ade_ev is not None:
        labels.append("ADE")
        calc_vals.append(summary.ade_ev)
        exp_vals.append(exp_map.get("ADE") or exp_map.get("ade"))
    if not labels:
        raise ValueError(f"Cluster {summary.cluster_label!r} has no VDE/ADE data")
    return FigureSpec(
        kind="vde_ade",
        title=f"{summary.cluster_label} VDE / ADE 计算与实验对比",
        subtitle="光电子能谱关键能量指标 (eV)",
        x_label="跃迁类型",
        y_label="能量 (eV)",
        filename_stem=f"{summary.cluster_label}_vde_ade",
        data={"labels": labels, "calculated_ev": calc_vals, "experimental_ev": exp_vals},
    )


def _build_s2_spec(result: CalcResult) -> FigureSpec:
    if result.s2_before is None and result.s2_after is None:
        raise ValueError(f"Job {result.job_id!r} has no <S^2> data")

    ideal = ideal_s_squared(result.state.multiplicity)
    ref_val = result.s2_after if result.s2_after is not None else result.s2_before
    contaminated = (
        is_spin_contaminated(ref_val, result.state.multiplicity) if ref_val is not None else False
    )
    labels: list[str] = []
    values: list[float] = []
    if result.s2_before is not None:
        labels.append("湮灭前 <S²>")
        values.append(result.s2_before)
    if result.s2_after is not None:
        labels.append("湮灭后 <S²>")
        values.append(result.s2_after)
    labels.append("理论值 S(S+1)")
    values.append(ideal)

    return FigureSpec(
        kind="s2",
        title=f"{result.job_id} 自旋期望值 <S²> 对比",
        subtitle=(
            f"M={result.state.multiplicity}, 理论 S(S+1)={ideal:.4f} | "
            + ("⚠️ 存在显著自旋污染 (>10%)" if contaminated else "自旋污染在允许范围内")
        ),
        x_label="状态",
        y_label="<S²>",
        filename_stem=f"{result.job_id}_s2",
        data={
            "labels": labels,
            "values": values,
            "ideal": ideal,
            "s2_before": result.s2_before,
            "s2_after": result.s2_after,
            "contaminated": contaminated,
        },
    )


def build_figure_spec(
    result: CalcResult,
    kind: Literal["levels", "spin", "dos", "s2"],
    *,
    fwhm_ev: float = 0.30,
    degen_tol_ev: float = 0.05,
) -> FigureSpec:
    """Build a FigureSpec from a single CalcResult for P1/CLI plot kinds."""
    if kind == "levels":
        return _build_levels_spec(result, degen_tol_ev=degen_tol_ev)
    if kind == "spin":
        return _build_spin_spec(result)
    if kind == "dos":
        return _build_dos_spec(result, fwhm_ev=fwhm_ev)
    if kind == "s2":
        return _build_s2_spec(result)
    raise ValueError(f"Unsupported single-result figure kind: {kind!r}")
