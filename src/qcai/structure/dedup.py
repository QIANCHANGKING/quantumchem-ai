"""Cluster deduplication via distance-eigenvalue fingerprint and RMSD matching."""

from __future__ import annotations

import numpy as np
from pymatgen.analysis.molecule_matcher import (
    BruteForceOrderMatcher,
    GeneticOrderMatcher,
    HungarianOrderMatcher,
)
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist

from qcai.core.models import Cluster
from qcai.core.physics import EV_TO_HA
from qcai.structure.readers import ScoredCluster


def distance_eigenvalue_fingerprint(cluster: Cluster) -> np.ndarray:
    """Compute sorted eigenvalues of the pairwise Euclidean distance matrix."""
    coords = np.asarray(cluster.positions, dtype=float)
    diff = coords[:, None, :] - coords[None, :, :]
    dmat = np.linalg.norm(diff, axis=-1)
    return np.sort(np.linalg.eigvalsh(dmat))


def inertia_aligned_hungarian_rmsd(c1: Cluster, c2: Cluster) -> float:
    """Order-independent RMSD by aligning 3 principal inertia axes + Hungarian + Kabsch."""
    m1 = c1.to_pymatgen()
    m2 = c2.to_pymatgen()
    if sorted(m1.atomic_numbers) != sorted(m2.atomic_numbers):
        return float("inf")

    p1 = np.asarray(m1.cart_coords, dtype=float) - np.asarray(m1.center_of_mass, dtype=float)
    p2 = np.asarray(m2.cart_coords, dtype=float) - np.asarray(m2.center_of_mass, dtype=float)
    w1 = np.asarray([s.species.weight for s in m1], dtype=float)
    w2 = np.asarray([s.species.weight for s in m2], dtype=float)

    def _axes(coords: np.ndarray, weights: np.ndarray) -> np.ndarray:
        cov = (coords.T * weights) @ coords
        _, eigvecs = np.linalg.eigh(cov)
        if np.linalg.det(eigvecs) < 0:
            eigvecs[:, 0] *= -1
        return eigvecs

    a1 = _axes(p1, w1)
    a2 = _axes(p2, w2)
    q1 = p1 @ a1

    sp1 = np.asarray(m1.atomic_numbers)
    sp2 = np.asarray(m2.atomic_numbers)
    best_rmsd = float("inf")

    for sgn in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)):
        q2 = p2 @ (a2 * np.asarray(sgn))
        perm = np.zeros(len(m1), dtype=np.int64)
        for z in np.unique(sp1):
            idx1 = np.where(sp1 == z)[0]
            idx2 = np.where(sp2 == z)[0]
            _, col_ind = linear_sum_assignment(cdist(q1[idx1], q2[idx2]))
            perm[idx1] = idx2[col_ind]
        p2_perm = p2[perm]
        rot = HungarianOrderMatcher.kabsch(p2_perm, p1)
        rmsd = float(np.sqrt(np.mean(np.sum((p2_perm @ rot - p1) ** 2, axis=1))))
        best_rmsd = min(best_rmsd, rmsd)
    return best_rmsd


def cluster_rmsd(c1: Cluster, c2: Cluster, *, threshold: float = 0.25) -> float:
    """Compute rotation-, translation-, and permutation-invariant RMSD between clusters."""
    if sorted(c1.symbols) != sorted(c2.symbols):
        return float("inf")

    rmsd = inertia_aligned_hungarian_rmsd(c1, c2)
    if rmsd <= threshold:
        return rmsd

    # High-symmetry clusters can have degenerate inertia eigenvalues where principal
    # axes are non-unique; fall back to pymatgen BruteForce/GeneticOrderMatcher.
    m1 = c1.to_pymatgen()
    m2 = c2.to_pymatgen()
    n_atoms = len(m1)
    if n_atoms <= 7:
        bf = BruteForceOrderMatcher(m1)
        _, bf_rmsd = bf.fit(m2)
        return float(min(rmsd, bf_rmsd))
    if n_atoms <= 24:
        gm = GeneticOrderMatcher(m1, threshold=max(threshold, 0.35))
        matches = gm.fit(m2)
        if matches:
            return float(min(rmsd, min(float(m[1]) for m in matches)))
    return rmsd


def deduplicate_clusters(
    candidates: list[ScoredCluster],
    *,
    energy_window_ev: float = 1.5,
    top_k: int = 8,
    rmsd_threshold: float = 0.25,
    fp_threshold: float = 0.35,
) -> list[ScoredCluster]:
    """Filter candidates by energy window and deduplicate using fingerprint + RMSD."""
    if not candidates:
        return []

    ordered = sorted(
        candidates,
        key=lambda sc: sc.energy_hartree if sc.energy_hartree is not None else float("inf"),
    )
    e_min = ordered[0].energy_hartree
    window_ha = energy_window_ev * EV_TO_HA

    unique: list[tuple[ScoredCluster, np.ndarray]] = []
    for cand in ordered:
        if (
            e_min is not None
            and cand.energy_hartree is not None
            and (cand.energy_hartree - e_min) > window_ha
        ):
            continue

        fp = distance_eigenvalue_fingerprint(cand.cluster)
        is_dup = False
        for kept, kept_fp in unique:
            if len(kept.cluster.symbols) != len(cand.cluster.symbols):
                continue
            if float(np.linalg.norm(fp - kept_fp)) > fp_threshold:
                continue
            if cluster_rmsd(kept.cluster, cand.cluster, threshold=rmsd_threshold) <= rmsd_threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append((cand, fp))
            if len(unique) >= top_k:
                break

    return [item[0] for item in unique]
