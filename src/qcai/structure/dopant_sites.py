"""Symmetry-inequivalent dopant site enumeration using PointGroupAnalyzer (Section 6.1)."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from typing import Any

import numpy as np
from pymatgen.symmetry.analyzer import PointGroupAnalyzer

from qcai.core.models import Cluster
from qcai.core.physics import covalent_radius


def _symmetry_atom_permutations(
    coords: np.ndarray,
    symm_ops: Sequence[Any],
    tol: float,
) -> list[tuple[int, ...]]:
    """Map each pymatgen SymmOp to an atom-index permutation on the skeleton."""
    n = len(coords)
    perms: list[tuple[int, ...]] = []
    for op in symm_ops:
        transformed = op.operate_multi(coords)
        dists = np.linalg.norm(transformed[:, None, :] - coords[None, :, :], axis=-1)
        nearest = np.argmin(dists, axis=1)
        min_d = dists[np.arange(n), nearest]
        if np.all(min_d <= tol) and len(set(nearest.tolist())) == n:
            perms.append(tuple(int(x) for x in nearest))
    if not perms:
        perms.append(tuple(range(n)))
    return list(dict.fromkeys(perms))


def enumerate_dopant_sites(
    host: Cluster,
    dopant_symbol: str,
    n_dopants: int = 1,
    *,
    try_endohedral: bool = True,
    tolerance: float = 0.3,
    eigen_tolerance: float = 0.01,
    max_raw_combinations: int = 5000,
) -> list[Cluster]:
    """Enumerate symmetry-inequivalent substitutional (and endohedral) dopant configurations."""
    if n_dopants < 1 or n_dopants >= len(host.symbols):
        raise ValueError(f"n_dopants ({n_dopants}) must be between 1 and {len(host.symbols) - 1}")

    mol = host.to_pymatgen()
    pga = PointGroupAnalyzer(mol, tolerance=tolerance, eigen_tolerance=eigen_tolerance)
    results: list[Cluster] = []

    if n_dopants == 1:
        eq_data = pga.get_equivalent_atoms()  # type: ignore[no-untyped-call]
        eq_sets: dict[int, list[int]] = eq_data["eq_sets"]
        for rep_idx in sorted(eq_sets):
            syms = list(host.symbols)
            syms[rep_idx] = dopant_symbol
            results.append(
                Cluster(
                    symbols=syms,
                    positions=list(host.positions),
                    label=f"{host.label}_sub_{dopant_symbol}_at_{rep_idx}",
                    source=f"dopant_sites:{pga.sch_symbol}",
                )
            )
    else:
        from math import comb

        n_atoms = len(host.symbols)
        total_combos = comb(n_atoms, n_dopants)
        if total_combos > max_raw_combinations:
            raise ValueError(
                f"Combinatorial count C({n_atoms},{n_dopants})={total_combos} exceeds limit "
                f"{max_raw_combinations}; delegate directly to global ABCluster/ASE-GA search."
            )

        coords = np.asarray(mol.cart_coords, dtype=float) - np.asarray(
            mol.center_of_mass, dtype=float
        )
        ops = pga.get_symmetry_operations()
        perms = _symmetry_atom_permutations(coords, ops, tol=max(tolerance, 0.35))

        seen_canonical: set[tuple[int, ...]] = set()
        for combo in combinations(range(n_atoms), n_dopants):
            canonical = min(tuple(sorted(perm[i] for i in combo)) for perm in perms)
            if canonical in seen_canonical:
                continue
            seen_canonical.add(canonical)
            syms = list(host.symbols)
            for idx in canonical:
                syms[idx] = dopant_symbol
            tag = "_".join(str(i) for i in canonical)
            results.append(
                Cluster(
                    symbols=syms,
                    positions=list(host.positions),
                    label=f"{host.label}_sub_{dopant_symbol}{n_dopants}_at_{tag}",
                    source=f"dopant_sites:{pga.sch_symbol}",
                )
            )

    # Check endohedral cavity at center of mass for hollow cage skeletons
    if try_endohedral and n_dopants == 1:
        coords = np.asarray(host.positions, dtype=float)
        center = np.mean(coords, axis=0)
        dists = np.linalg.norm(coords - center, axis=1)
        r_dop = covalent_radius(dopant_symbol)
        min_allowed = [0.8 * (covalent_radius(sym) + r_dop) for sym in host.symbols]
        if all(float(d) >= thr for d, thr in zip(dists, min_allowed, strict=True)):
            results.append(
                Cluster(
                    symbols=[dopant_symbol, *host.symbols],
                    positions=[
                        (float(center[0]), float(center[1]), float(center[2])),
                        *host.positions,
                    ],
                    label=f"{dopant_symbol}_at_{host.label}_endo",
                    source=f"dopant_sites:endohedral:{pga.sch_symbol}",
                )
            )

    return results
