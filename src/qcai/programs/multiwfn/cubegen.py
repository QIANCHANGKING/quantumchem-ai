"""Gaussian cubegen command templates for preview and publication grids."""

from __future__ import annotations

from typing import Literal

CUBE_GRID_PRESETS: dict[Literal["preview", "publication"], str] = {
    "preview": "40",
    "publication": "100",
}


def build_cubegen_jobs(
    fchk_name: str,
    *,
    open_shell: bool,
    quality: Literal["preview", "publication"] = "preview",
) -> list[tuple[str, list[str]]]:
    """Return `(label, cubegen_argv)` pairs for spin density and frontier orbitals."""
    npts = CUBE_GRID_PRESETS[quality]
    stem = fchk_name.rsplit(".", 1)[0]
    specs: list[tuple[str, str]]
    if open_shell:
        specs = [
            ("spin", "Spin=SCF"),
            ("homo_alpha", "AMO=HOMO"),
            ("homo_beta", "BMO=HOMO"),
            ("lumo_alpha", "AMO=LUMO"),
            ("lumo_beta", "BMO=LUMO"),
        ]
    else:
        specs = [
            ("homo", "MO=HOMO"),
            ("lumo", "MO=LUMO"),
        ]

    jobs: list[tuple[str, list[str]]] = []
    for label, kind in specs:
        out_cube = f"{stem}_{label}.cube"
        jobs.append((label, ["cubegen", "0", kind, fchk_name, out_cube, npts, "h"]))
    return jobs
