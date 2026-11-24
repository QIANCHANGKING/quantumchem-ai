"""Matplotlib fallback and CI/test 2D figure renderer supporting all 10 plot kinds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from qcai.interfaces.renderer import FigureRenderer
from qcai.renderers.spec import FigureSpec

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


class MatplotlibRenderer(FigureRenderer):
    """Render any FigureSpec to PNG and SVG using Matplotlib."""

    name = "mpl"

    def render(self, spec: FigureSpec, out_dir: Path) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if spec.kind == "size_evolution":
            fig = self._render_size_evolution(spec)
        else:
            fig, ax = plt.subplots(figsize=(7.5, 5.2), dpi=150)
            dispatch = {
                "levels": self._draw_levels,
                "levels_compare": self._draw_levels_compare,
                "spin": self._draw_spin,
                "dos": self._draw_dos,
                "orb_comp": self._draw_orb_comp,
                "spin_ladder": self._draw_spin_ladder,
                "isomer_ranking": self._draw_isomer_ranking,
                "vde_ade": self._draw_vde_ade,
                "s2": self._draw_s2,
            }
            handler = dispatch.get(spec.kind)
            if handler is None:
                plt.close(fig)
                raise ValueError(f"Unsupported figure kind for MatplotlibRenderer: {spec.kind!r}")
            handler(ax, spec)
            fig.suptitle(spec.title, fontsize=13, fontweight="bold", y=0.98)
            if spec.subtitle:
                ax.set_title(spec.subtitle, fontsize=10, color="#444444", pad=10)
            fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.94))

        png_path = out_dir / f"{spec.filename_stem}.png"
        svg_path = out_dir / f"{spec.filename_stem}.svg"
        fig.savefig(png_path, dpi=300)
        fig.savefig(svg_path)
        plt.close(fig)
        return [png_path, svg_path]

    def _draw_levels(self, ax: Axes, spec: FigureSpec) -> None:
        channels: list[dict[str, Any]] = spec.data["channels"]
        open_shell: bool = bool(spec.data["open_shell"])
        centers = [0.35, 0.75] if open_shell else [0.5]
        labels = ["α 自旋", "β 自旋"] if open_shell else ["轨道能级"]

        for idx, ch in enumerate(channels):
            cx = centers[idx]
            for orb in ch["orbitals"]:
                deg = max(1, int(orb["degeneracy"]))
                slot = int(orb["slot"])
                total_w = 0.24
                seg_w = total_w / deg
                x0 = cx - total_w / 2.0 + slot * seg_w + 0.008
                x1 = x0 + seg_w - 0.016
                if x1 <= x0:
                    x0, x1 = cx - 0.08, cx + 0.08
                occ = bool(orb["occupied"])
                color = "#1f4e78" if occ else "#d95f02"
                ls = "-" if occ else "--"
                e = float(orb["energy_ev"])
                ax.plot([x0, x1], [e, e], color=color, linestyle=ls, linewidth=1.8)

                if orb["is_homo"]:
                    tag = "HOMO" if not open_shell else f"HOMO({ch['name'][0]})"
                    ax.text(
                        cx + total_w / 2.0 + 0.015,
                        e,
                        f"{tag} {e:.2f}",
                        va="center",
                        fontsize=8,
                        color="#1f4e78",
                        fontweight="bold",
                    )
                elif orb["is_lumo"]:
                    tag = "LUMO" if not open_shell else f"LUMO({ch['name'][0]})"
                    ax.text(
                        cx + total_w / 2.0 + 0.015,
                        e,
                        f"{tag} {e:.2f}",
                        va="center",
                        fontsize=8,
                        color="#d95f02",
                        fontweight="bold",
                    )

            homo_ev, lumo_ev, gap_ev = ch.get("homo_ev"), ch.get("lumo_ev"), ch.get("gap_ev")
            if homo_ev is not None and lumo_ev is not None and gap_ev is not None:
                ax.annotate(
                    "",
                    xy=(cx, float(lumo_ev)),
                    xytext=(cx, float(homo_ev)),
                    arrowprops={"arrowstyle": "<->", "color": "#555555", "lw": 1.1},
                )
                ax.text(
                    cx - 0.02,
                    0.5 * (float(homo_ev) + float(lumo_ev)),
                    f"Eg={float(gap_ev):.2f}",
                    ha="right",
                    va="center",
                    fontsize=8,
                    color="#333333",
                )

        ax.set_xlim(0.05, 1.05)
        ax.set_xticks(centers[: len(channels)])
        ax.set_xticklabels(labels[: len(channels)])
        ax.set_ylabel(spec.y_label)
        ax.grid(axis="y", linestyle=":", alpha=0.4)

    def _draw_levels_compare(self, ax: Axes, spec: FigureSpec) -> None:
        series: list[dict[str, Any]] = spec.data["series"]
        xs = list(range(len(series)))
        for idx, item in enumerate(series):
            for e in item["occ_ev"]:
                ax.plot([idx - 0.25, idx + 0.25], [e, e], color="#1f4e78", lw=1.8)
            for e in item["virt_ev"]:
                ax.plot([idx - 0.25, idx + 0.25], [e, e], color="#d95f02", ls="--", lw=1.6)
            if item.get("gap_ev") is not None and item.get("homo_ev") is not None:
                ax.text(
                    idx,
                    float(item["homo_ev"]) - 0.35,
                    f"Eg={float(item['gap_ev']):.2f}",
                    ha="center",
                    fontsize=8,
                )
        ax.set_xticks(xs)
        ax.set_xticklabels([it["label"] for it in series])
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.grid(axis="y", linestyle=":", alpha=0.4)

    def _draw_spin(self, ax: Axes, spec: FigureSpec) -> None:
        labels: list[str] = spec.data["atom_labels"]
        values: list[float] = spec.data["spin_values"]
        highlighted: list[bool] = spec.data["highlighted"]
        colors = ["#d62728" if h else "#2b6cb0" for h in highlighted]
        xs = list(range(len(labels)))
        ax.bar(xs, values, color=colors, edgecolor="#222222", linewidth=0.6)
        ax.axhline(0.0, color="#444444", linewidth=0.9)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=45 if len(labels) > 10 else 0, fontsize=8)
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.grid(axis="y", linestyle=":", alpha=0.4)

    def _draw_dos(self, ax: Axes, spec: FigureSpec) -> None:
        energies: list[float] = spec.data["energies_ev"]
        tdos_alpha: list[float] = spec.data["tdos_alpha"]
        tdos_beta: list[float] | None = spec.data.get("tdos_beta")
        open_shell: bool = bool(spec.data["open_shell"])

        ax.plot(energies, tdos_alpha, color="#1f4e78", linewidth=1.6, label="TDOS (α)")
        ax.fill_between(energies, 0.0, tdos_alpha, color="#1f4e78", alpha=0.12)
        if tdos_alpha:
            max_a = max(tdos_alpha)
            for stick in spec.data.get("sticks_alpha_ev", []):
                ax.plot([stick, stick], [0.0, max_a * 0.12], color="#1f4e78", lw=0.7)

        for pdos_name, pdos_vals in spec.data.get("pdos_series", {}).items():
            if len(pdos_vals) == len(energies):
                ax.plot(energies, pdos_vals, linewidth=1.1, alpha=0.85, label=f"PDOS ({pdos_name})")

        if open_shell and tdos_beta is not None:
            ax.plot(energies, tdos_beta, color="#c0392b", linewidth=1.6, label="TDOS (β)")
            ax.fill_between(energies, 0.0, tdos_beta, color="#c0392b", alpha=0.12)
            min_beta = min(tdos_beta) if tdos_beta else -1.0
            for stick in spec.data.get("sticks_beta_ev", []):
                ax.plot([stick, stick], [0.0, min_beta * 0.12], color="#c0392b", lw=0.7)
            ax.axhline(0.0, color="#333333", linewidth=0.9)

        homo_ev = spec.data.get("homo_alpha_ev")
        if homo_ev is not None:
            ax.axvline(
                float(homo_ev),
                color="#2e7d32",
                linestyle="--",
                linewidth=1.2,
                label=f"HOMO ({float(homo_ev):.2f} eV)",
            )

        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.legend(loc="upper right", fontsize=7)
        ax.grid(True, linestyle=":", alpha=0.4)

    def _draw_orb_comp(self, ax: Axes, spec: FigureSpec) -> None:
        orb_labels: list[str] = spec.data["orbital_labels"]
        series: dict[str, list[float]] = spec.data["series"]
        xs = np.arange(len(orb_labels))
        bottom = np.zeros(len(orb_labels))
        palette = {"S": "#1f77b4", "P": "#ff7f0e", "D": "#2ca02c", "F": "#9467bd"}
        for name, vals in series.items():
            arr = np.asarray(vals, dtype=float)
            ax.bar(
                xs,
                arr,
                bottom=bottom,
                label=f"{name} 轨道",
                color=palette.get(name, "#7f7f7f"),
                edgecolor="#222222",
                linewidth=0.5,
            )
            bottom += arr
        ax.set_xticks(xs)
        ax.set_xticklabels(orb_labels, fontsize=8)
        ax.set_ylim(0.0, 105.0)
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(axis="y", linestyle=":", alpha=0.4)

    def _draw_spin_ladder(self, ax: Axes, spec: FigureSpec) -> None:
        mults: list[int] = spec.data["multiplicities"]
        energies: list[float] = spec.data["rel_energies_ev"]
        for m, e in zip(mults, energies, strict=True):
            ax.plot([m - 0.35, m + 0.35], [e, e], color="#1f4e78", linewidth=2.5)
            ax.text(m, e + 0.02, f"{e:.3f}", ha="center", va="bottom", fontsize=8)
        ax.plot(mults, energies, color="#888888", linestyle=":", linewidth=1.0)
        ax.set_xticks(mults)
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.grid(axis="y", linestyle=":", alpha=0.4)

    def _draw_isomer_ranking(self, ax: Axes, spec: FigureSpec) -> None:
        labels: list[str] = spec.data["labels"]
        energies: list[float] = spec.data["rel_energies_ev"]
        xs = list(range(len(labels)))
        colors = ["#2e7d32" if i == 0 else "#4c72b0" for i in xs]
        ax.bar(xs, energies, color=colors, edgecolor="#222222", linewidth=0.6)
        for x, e in zip(xs, energies, strict=True):
            ax.text(x, e, f"{e:.3f}", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.grid(axis="y", linestyle=":", alpha=0.4)

    def _draw_vde_ade(self, ax: Axes, spec: FigureSpec) -> None:
        labels: list[str] = spec.data["labels"]
        calc_vals: list[float] = spec.data["calculated_ev"]
        exp_vals: list[float | None] = spec.data["experimental_ev"]
        xs = np.arange(len(labels))
        width = 0.32
        has_exp = any(v is not None for v in exp_vals)
        if has_exp:
            ax.bar(xs - width / 2, calc_vals, width=width, label="理论计算", color="#1f4e78")
            exp_clean = [float(v) if v is not None else 0.0 for v in exp_vals]
            ax.bar(xs + width / 2, exp_clean, width=width, label="实验值", color="#d95f02")
            ax.legend(fontsize=8)
        else:
            ax.bar(xs, calc_vals, width=0.45, label="理论计算", color="#1f4e78")
        for i, v in enumerate(calc_vals):
            ax.text(
                i - (width / 2 if has_exp else 0.0),
                v,
                f"{v:.3f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )
        ax.set_xticks(xs)
        ax.set_xticklabels(labels)
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.grid(axis="y", linestyle=":", alpha=0.4)

    def _render_size_evolution(self, spec: FigureSpec) -> Figure:
        sizes: list[int] = spec.data["sizes"]
        panels = [
            ("eb_ev", r"平均结合能 $E_b$ (eV/atom)", "#1f4e78"),
            ("delta2_e_ev", r"二阶能量差分 $\Delta_2 E$ (eV)", "#d95f02"),
            ("gap_ev", r"HOMO-LUMO 能隙 $E_g$ (eV)", "#2e7d32"),
            ("mu_b", r"总磁矩 $\mu$ ($\mu_B$)", "#9467bd"),
        ]
        fig, axes = plt.subplots(2, 2, figsize=(9.2, 6.8), dpi=150, sharex=True)
        for ax, (key, ylabel, color) in zip(axes.flat, panels, strict=True):
            vals = spec.data.get(key, [])
            pts = [(s, float(v)) for s, v in zip(sizes, vals, strict=True) if v is not None]
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", color=color, lw=1.8)
            if key == "delta2_e_ev":
                ax.axhline(0.0, color="#666666", ls="--", lw=0.8)
            ax.set_ylabel(ylabel, fontsize=9)
            ax.grid(True, linestyle=":", alpha=0.4)
        axes[1, 0].set_xlabel(spec.x_label)
        axes[1, 1].set_xlabel(spec.x_label)
        fig.suptitle(spec.title, fontsize=13, fontweight="bold", y=0.98)
        fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.94))
        return fig

    def _draw_s2(self, ax: Axes, spec: FigureSpec) -> None:
        labels: list[str] = spec.data["labels"]
        values: list[float] = spec.data["values"]
        ideal = float(spec.data["ideal"])
        xs = list(range(len(labels)))
        colors = ["#4c72b0"] * (len(labels) - 1) + ["#2e7d32"]
        ax.bar(xs, values, color=colors, width=0.5, edgecolor="#222222", linewidth=0.6)
        ax.axhline(ideal, color="#2e7d32", linestyle="--", linewidth=1.1, label="理论 S(S+1)")
        if ideal > 0:
            ax.axhspan(
                ideal * 0.9,
                ideal * 1.1,
                color="#2e7d32",
                alpha=0.1,
                label="±10% 允许区",
            )
        for x, v in zip(xs, values, strict=True):
            ax.text(x, v, f"{v:.4f}", ha="center", va="bottom", fontsize=9)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels)
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(axis="y", linestyle=":", alpha=0.4)
