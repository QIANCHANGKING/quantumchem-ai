"""Publication-grade VMD Tcl + TachyonInternal batch renderer (Section 6.7)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

from qcai.config import load_settings
from qcai.core.models import Cluster
from qcai.renderers.web3d.viewer import align_cluster_principal_axes, minority_atom_indices


def build_vmd_tcl(
    xyz_path: Path,
    tga_path: Path,
    *,
    cube_path: Path | None = None,
    isovalue: float = 0.03,
    dopant_indices: list[int] | None = None,
) -> str:
    """Generate a VMD Tcl script rendering cluster geometry and optional cube isosurfaces."""
    lines = [
        f"mol new {{{xyz_path.resolve().as_posix()}}} type xyz waitfor all",
        "display projection Orthographic",
        "display shadows on",
        "display ambientocclusion on",
        "color Display Background white",
        "axes location Off",
        "mol delrep 0 top",
        "mol representation CPK 1.0 0.32 28 28",
        "mol color Name",
        "mol material AOShiny",
        "mol addrep top",
    ]

    if dopant_indices:
        idx_str = " ".join(str(i) for i in dopant_indices)
        lines.extend(
            [
                "mol representation CPK 1.15 0.36 28 28",
                "mol color ColorID 3",
                f"mol selection {{index {idx_str}}}",
                "mol material AOShiny",
                "mol addrep top",
            ]
        )

    if cube_path is not None and cube_path.exists():
        lines.extend(
            [
                f"mol addfile {{{cube_path.resolve().as_posix()}}} type cube waitfor all",
                f"mol representation Isosurface {isovalue:.4f} 0 0 0 1 1",
                "mol color ColorID 1",
                "mol material Transparent",
                "mol addrep top",
                f"mol representation Isosurface {-isovalue:.4f} 0 0 0 1 1",
                "mol color ColorID 0",
                "mol material Transparent",
                "mol addrep top",
            ]
        )

    lines.extend(
        [
            "reset view",
            f"render TachyonInternal {{{tga_path.resolve().as_posix()}}}",
            "quit",
        ]
    )
    return "\n".join(lines) + "\n"


class VmdRenderer:
    """Render publication-quality 3D cluster/orbital images via Windows VMD."""

    def __init__(self, executable: Path | None = None, *, timeout_seconds: float = 60.0) -> None:
        if executable is None:
            cfg = load_settings()
            executable = Path(cfg.vmd.executable) if cfg.vmd.executable else None
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def render_cluster(
        self,
        cluster: Cluster,
        out_dir: Path,
        *,
        cube_path: Path | None = None,
        isovalue: float = 0.03,
        stem: str | None = None,
    ) -> list[Path]:
        """Align cluster to principal axes, package .tcl/.xyz/.cube, and render PNG via VMD."""
        if self.executable is None or not self.executable.exists():
            raise RuntimeError(f"VMD executable not configured or missing: {self.executable}")

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = stem or cluster.label

        aligned = align_cluster_principal_axes(cluster)
        xyz_path = out_dir / f"{tag}.xyz"
        xyz_lines = [str(len(aligned.symbols)), aligned.label]
        for sym, (x, y, z) in zip(aligned.symbols, aligned.positions, strict=True):
            xyz_lines.append(f"{sym:4s} {x:12.6f} {y:12.6f} {z:12.6f}")
        xyz_path.write_text("\n".join(xyz_lines) + "\n", encoding="utf-8")

        staged_cube: Path | None = None
        if cube_path is not None and Path(cube_path).exists():
            staged_cube = out_dir / Path(cube_path).name
            if staged_cube.resolve() != Path(cube_path).resolve():
                shutil.copy2(cube_path, staged_cube)

        tga_path = out_dir / f"{tag}_vmd.tga"
        png_path = out_dir / f"{tag}_vmd.png"
        tcl_path = out_dir / f"{tag}_vmd.tcl"
        for p in (tga_path, png_path):
            if p.exists():
                p.unlink()

        dop_idx = minority_atom_indices(aligned.symbols)
        tcl_text = build_vmd_tcl(
            xyz_path,
            tga_path,
            cube_path=staged_cube,
            isovalue=isovalue,
            dopant_indices=dop_idx,
        )
        tcl_path.write_text(tcl_text, encoding="utf-8")

        subprocess.run(
            [str(self.executable), "-dispdev", "text", "-e", str(tcl_path)],
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        # Note: Windows VMD can return 0xC0000374 (3221226356) on Tcl exit teardown
        # after successfully writing the rendered TGA image.
        if not tga_path.exists() or tga_path.stat().st_size == 0:
            raise RuntimeError(f"VMD failed to produce rendered TGA image at {tga_path}")

        with Image.open(tga_path) as img:
            img.save(png_path)

        outputs = [png_path, tcl_path, xyz_path]
        if staged_cube is not None:
            outputs.append(staged_cube)
        return outputs
