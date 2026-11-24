"""py3Dmol interactive 3D cluster and cube isosurface viewer (Section 6.7)."""

from __future__ import annotations

from collections import Counter

import numpy as np
import py3Dmol
from ase.data import atomic_masses, atomic_numbers

from qcai.core.models import Cluster


def align_cluster_principal_axes(cluster: Cluster) -> Cluster:
    """Center at center-of-mass and align coordinates to principal axes of inertia.

    Shared by py3Dmol web preview and VMD publication renderer so both share the
    exact same default viewing orientation (Section 3.2).
    """
    coords = np.asarray(cluster.positions, dtype=float)
    masses = np.asarray(
        [float(atomic_masses[atomic_numbers[sym]]) for sym in cluster.symbols],
        dtype=float,
    )
    com = np.average(coords, axis=0, weights=masses)
    centered = coords - com
    inertia = (centered.T * masses) @ centered
    eigvals, eigvecs = np.linalg.eigh(inertia)
    # Sort descending so largest spread aligns along X, second along Y, smallest along Z
    order = np.argsort(eigvals)[::-1]
    axes = eigvecs[:, order]
    if np.linalg.det(axes) < 0:
        axes[:, 2] *= -1
    aligned = centered @ axes
    return Cluster(
        symbols=list(cluster.symbols),
        positions=[(float(x), float(y), float(z)) for x, y, z in aligned],
        label=cluster.label,
        source=cluster.source,
    )


def _cluster_to_xyz(cluster: Cluster) -> str:
    lines = [str(len(cluster.symbols)), cluster.label]
    for sym, (x, y, z) in zip(cluster.symbols, cluster.positions, strict=True):
        lines.append(f"{sym:4s} {x:12.6f} {y:12.6f} {z:12.6f}")
    return "\n".join(lines) + "\n"


def minority_atom_indices(symbols: list[str]) -> list[int]:
    """Identify minority-element indices for automatic dopant highlighting (Axiom A2)."""
    counts = Counter(symbols)
    if len(counts) <= 1:
        return []
    min_cnt = min(counts.values())
    return [i for i, sym in enumerate(symbols) if counts[sym] == min_cnt]


def build_py3dmol_html(
    cluster: Cluster,
    *,
    cube_text: str | None = None,
    isovalue: float = 0.03,
    width: int = 640,
    height: int = 440,
) -> str:
    """Generate embeddable py3Dmol HTML for Streamlit components.html."""
    aligned = align_cluster_principal_axes(cluster)
    xyz_str = _cluster_to_xyz(aligned)

    view = py3Dmol.view(width=width, height=height)
    view.addModel(xyz_str, "xyz")
    view.setStyle({}, {"stick": {"radius": 0.14}, "sphere": {"scale": 0.34}})

    dop_idx = minority_atom_indices(aligned.symbols)
    if dop_idx:
        view.setStyle(
            {"index": dop_idx},
            {
                "stick": {"radius": 0.16, "color": "#e67e22"},
                "sphere": {"scale": 0.40, "color": "#e67e22"},
            },
        )

    if cube_text:
        view.addVolumetricData(
            cube_text,
            "cube",
            {"isoval": float(isovalue), "color": "#d62728", "opacity": 0.72},
        )
        view.addVolumetricData(
            cube_text,
            "cube",
            {"isoval": -float(isovalue), "color": "#1f77b4", "opacity": 0.72},
        )

    view.setBackgroundColor("#ffffff")
    view.zoomTo()
    return str(view._make_html())
