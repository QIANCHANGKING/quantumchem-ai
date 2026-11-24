"""Structure readers for XYZ, multi-frame XYZ, ABCluster LM, and molclus outputs."""

from __future__ import annotations

import re
from pathlib import Path

from ase.io import read as ase_read
from pydantic import BaseModel, Field

from qcai.core.models import Cluster

_FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eEdD][-+]?\d+)?")
_EV_UNIT_RE = re.compile(r"\beV\b", re.IGNORECASE)
_ENERGY_KEY_RE = re.compile(
    r"(?:energy\s*=\s*|E\s*=\s*)([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)


class ScoredCluster(BaseModel):
    """Cluster structure paired with optional energy (Hartree) and search metadata."""

    cluster: Cluster
    energy_hartree: float | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


def parse_xyz_comment_energy(comment: str) -> float | None:
    """Extract energy in Hartree from an XYZ comment line (ABCluster / xTB / molclus)."""
    from qcai.core.physics import EV_TO_HA

    text = comment.strip()
    if not text:
        return None

    m = _ENERGY_KEY_RE.search(text)
    if m:
        val = float(m.group(1))
        return val * EV_TO_HA if _EV_UNIT_RE.search(text) else val

    # ABCluster / xTB standard: comment is purely a float or "energy: <float>"
    tokens = text.replace("D", "E").split()
    for tok in tokens:
        if _FLOAT_RE.fullmatch(tok):
            val = float(tok)
            return val * EV_TO_HA if _EV_UNIT_RE.search(text) else val
    return None


def _read_xyz_comments(path: Path) -> list[str]:
    """Read comment lines from single- or multi-frame XYZ files."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    comments: list[str] = []
    idx = 0
    while idx < len(lines):
        header = lines[idx].strip()
        if not header:
            idx += 1
            continue
        try:
            n_atoms = int(header)
        except ValueError:
            break
        if idx + 1 < len(lines):
            comments.append(lines[idx + 1])
        idx += 2 + n_atoms
    return comments


def read_clusters_from_file(path: Path, *, label_prefix: str | None = None) -> list[ScoredCluster]:
    """Read single or multi-frame structure files via ASE and extract energies when XYZ."""
    p = Path(path)
    frames = ase_read(str(p), index=":")
    if not isinstance(frames, list):
        frames = [frames]

    comments = _read_xyz_comments(p) if p.suffix.lower() == ".xyz" else []
    prefix = label_prefix or p.stem
    results: list[ScoredCluster] = []
    for i, atoms in enumerate(frames):
        energy: float | None = None
        if i < len(comments):
            energy = parse_xyz_comment_energy(comments[i])
        elif "energy" in atoms.info:
            energy = float(atoms.info["energy"])
        lbl = f"{prefix}_{i}" if len(frames) > 1 else prefix
        cluster = Cluster.from_ase(atoms, label=lbl, source=str(p))
        results.append(ScoredCluster(cluster=cluster, energy_hartree=energy))
    return results


def read_abcluster_lm_dir(lm_dir: Path) -> list[ScoredCluster]:
    """Read all `*.xyz` local minima from an ABCluster `-LM` directory, sorted by energy."""
    d = Path(lm_dir)
    if not d.exists():
        return []
    xyz_files = sorted(
        d.glob("*.xyz"),
        key=lambda f: int(f.stem) if f.stem.isdigit() else 10**9,
    )
    items: list[ScoredCluster] = []
    for xyz in xyz_files:
        items.extend(read_clusters_from_file(xyz, label_prefix=f"abc_{xyz.stem}"))
    items.sort(key=lambda sc: sc.energy_hartree if sc.energy_hartree is not None else float("inf"))
    return items
