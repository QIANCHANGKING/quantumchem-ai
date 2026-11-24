"""Spike 02: Verify pymatgen PointGroupAnalyzer tolerances on clusters."""

import numpy as np
from pymatgen.core import Molecule
from pymatgen.symmetry.analyzer import PointGroupAnalyzer


def make_octahedron(d: float = 2.0) -> Molecule:
    coords = [
        (d, 0.0, 0.0),
        (-d, 0.0, 0.0),
        (0.0, d, 0.0),
        (0.0, -d, 0.0),
        (0.0, 0.0, d),
        (0.0, 0.0, -d),
    ]
    return Molecule(["Au"] * 6, coords)


def make_icosahedron_centered(r: float = 2.6) -> Molecule:
    phi = (1.0 + np.sqrt(5.0)) / 2.0
    raw = [
        (0, 1, phi),
        (0, -1, phi),
        (0, 1, -phi),
        (0, -1, -phi),
        (1, phi, 0),
        (-1, phi, 0),
        (1, -phi, 0),
        (-1, -phi, 0),
        (phi, 0, 1),
        (-phi, 0, 1),
        (phi, 0, -1),
        (-phi, 0, -1),
    ]
    scale = r / np.linalg.norm(raw[0])
    coords = [(0.0, 0.0, 0.0)] + [tuple(np.array(c) * scale) for c in raw]
    return Molecule(["Ni"] + ["Al"] * 12, coords)


def perturb(mol: Molecule, sigma: float, seed: int = 42) -> Molecule:
    rng = np.random.default_rng(seed)
    coords = np.array(mol.cart_coords) + rng.normal(0.0, sigma, size=(len(mol), 3))
    return Molecule(mol.species, coords)


def main() -> None:
    oh = make_octahedron()
    ih = make_icosahedron_centered()

    for name, mol in [("Oh Au6", oh), ("Ih Ni@Al12", ih)]:
        pga = PointGroupAnalyzer(mol, tolerance=0.3, eigen_tolerance=0.01)
        eq = pga.get_equivalent_atoms()
        ops = pga.get_symmetry_operations()
        print(
            f"{name} (ideal): pg={pga.sch_symbol}, "
            f"eq_sets={len(set(eq['eq_sets'].keys()))}, ops={len(ops)}"
        )

    print("\n=== Perturbed Ih Ni@Al12 tolerance sweep ===")
    for sigma in [0.005, 0.02, 0.05, 0.10]:
        pmol = perturb(ih, sigma)
        row = []
        for tol in [0.1, 0.3, 0.5]:
            pga = PointGroupAnalyzer(pmol, tolerance=tol, eigen_tolerance=0.02)
            eq_sets = len(set(pga.get_equivalent_atoms()["eq_sets"].keys()))
            row.append(f"tol={tol}:{pga.sch_symbol}({eq_sets})")
        print(f"sigma={sigma:.3f} A -> " + " | ".join(row))

    print("\nPASS: spike_02_pointgroup")


if __name__ == "__main__":
    main()
