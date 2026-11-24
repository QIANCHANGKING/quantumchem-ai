"""Spike 03: Benchmark structure deduplication (eigenvalue fingerprint + molecule matchers)."""

import time

import numpy as np
from pymatgen.analysis.molecule_matcher import (
    BruteForceOrderMatcher,
    GeneticOrderMatcher,
    HungarianOrderMatcher,
)
from pymatgen.core import Molecule
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist


def random_cluster(n: int, seed: int = 0) -> Molecule:
    rng = np.random.default_rng(seed)
    coords = rng.uniform(-3.0, 3.0, size=(n, 3))
    species = ["Au"] * (n // 2) + ["Ag"] * (n - n // 2)
    return Molecule(species, coords)


def transform_and_permute(mol: Molecule, seed: int = 1) -> Molecule:
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    shift = rng.uniform(-10, 10, size=3)
    perm = rng.permutation(len(mol))
    coords = (np.array(mol.cart_coords) @ q.T + shift)[perm]
    species = [mol.species[i] for i in perm]
    return Molecule(species, coords)


def dist_eig_fingerprint(mol: Molecule) -> np.ndarray:
    coords = np.array(mol.cart_coords)
    diff = coords[:, None, :] - coords[None, :, :]
    dmat = np.linalg.norm(diff, axis=-1)
    return np.sort(np.linalg.eigvalsh(dmat))


def inertia_aligned_hungarian_rmsd(m1: Molecule, m2: Molecule) -> float:
    """Align 3 principal axes (4 proper rotations) + per-species Hungarian + Kabsch."""
    c1 = np.array(m1.cart_coords) - np.array(m1.center_of_mass)
    c2 = np.array(m2.cart_coords) - np.array(m2.center_of_mass)
    w1 = np.array([s.species.weight for s in m1])
    w2 = np.array([s.species.weight for s in m2])

    def axes(c: np.ndarray, w: np.ndarray) -> np.ndarray:
        cov = (c.T * w) @ c
        _, eigvecs = np.linalg.eigh(cov)
        if np.linalg.det(eigvecs) < 0:
            eigvecs[:, 0] *= -1
        return eigvecs

    a1 = axes(c1, w1)
    a2 = axes(c2, w2)
    q1 = c1 @ a1

    sp1 = np.array(m1.atomic_numbers)
    sp2 = np.array(m2.atomic_numbers)
    best_rmsd = float("inf")
    flips = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    for sgn in flips:
        q2 = c2 @ (a2 * np.array(sgn))
        perm = np.zeros(len(m1), dtype=np.int64)
        for z in np.unique(sp1):
            idx1 = np.where(sp1 == z)[0]
            idx2 = np.where(sp2 == z)[0]
            _, col_ind = linear_sum_assignment(cdist(q1[idx1], q2[idx2]))
            perm[idx1] = idx2[col_ind]
        p_aligned = c2[perm]
        u = HungarianOrderMatcher.kabsch(p_aligned, c1)
        rmsd = float(np.sqrt(np.mean(np.sum((p_aligned @ u - c1) ** 2, axis=1))))
        best_rmsd = min(best_rmsd, rmsd)
    return best_rmsd


def main() -> None:
    print("=== Correctness & speed test ===")
    for n in [6, 13, 20, 38]:
        m1 = random_cluster(n, seed=n)
        m2 = transform_and_permute(m1, seed=n + 100)
        m3 = random_cluster(n, seed=n + 999)

        t0 = time.perf_counter()
        fp1 = dist_eig_fingerprint(m1)
        fp2 = dist_eig_fingerprint(m2)
        fp3 = dist_eig_fingerprint(m3)
        fp_same = float(np.linalg.norm(fp1 - fp2))
        fp_other = float(np.linalg.norm(fp1 - fp3))
        t_fp = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        hm = HungarianOrderMatcher(m1)
        _, hm_same = hm.fit(m2)
        t_hm = (time.perf_counter() - t1) * 1000

        t2 = time.perf_counter()
        ia_same = inertia_aligned_hungarian_rmsd(m1, m2)
        ia_other = inertia_aligned_hungarian_rmsd(m1, m3)
        t_ia = (time.perf_counter() - t2) * 1000

        ga_info = "skipped"
        if n <= 20:
            t3 = time.perf_counter()
            gm = GeneticOrderMatcher(m1, threshold=0.3)
            res = gm.fit(m2)
            t_ga = (time.perf_counter() - t3) * 1000
            ga_rmsd = res[0][1] if res else float("inf")
            ga_info = f"GA={ga_rmsd:.2e} ({t_ga:.1f} ms)"

        bf_info = "skipped"
        if n <= 10:
            bf = BruteForceOrderMatcher(m1)
            _, bf_rmsd = bf.fit(m2)
            bf_info = f"BF={bf_rmsd:.2e}"

        print(
            f"N={n:2d}: fp_same={fp_same:.2e}, fp_other={fp_other:.2f} ({t_fp:.2f}ms) | "
            f"pmg_Hungarian={hm_same:.2f} ({t_hm:.2f}ms) | "
            f"3axis_Hungarian same={ia_same:.2e}, other={ia_other:.2f} ({t_ia:.2f}ms) | "
            f"{ga_info} | {bf_info}"
        )
        assert fp_same < 1e-10
        assert ia_same < 1e-10

    print("\nPASS: spike_03_dedup")


if __name__ == "__main__":
    main()
