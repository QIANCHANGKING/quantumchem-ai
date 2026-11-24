"""Spike 01: Verify pymatgen Element attributes and ASE ground_state_magnetic_moments."""

from ase.data import atomic_numbers, covalent_radii, ground_state_magnetic_moments
from pymatgen.core import Element


def main() -> None:
    targets = {"Fe": 5, "Co": 4, "Ni": 3, "Cu": 2, "Au": 2, "Pt": 3}
    print("=== Spot-check atomic ground-state multiplicities ===")
    for sym, expected_mult in targets.items():
        z = atomic_numbers[sym]
        magmom = float(ground_state_magnetic_moments[z])
        mult = int(round(magmom)) + 1
        el = Element(sym)
        print(
            f"{sym} (Z={z}): magmom={magmom}, mult={mult} (expected={expected_mult}), "
            f"period={el.row}, group={el.group}, block={el.block}, "
            f"TM={el.is_transition_metal}, Ln={el.is_lanthanoid}, Ac={el.is_actinoid}, "
            f"r_cov={covalent_radii[z]:.3f}"
        )
        assert mult == expected_mult, f"Mismatch for {sym}: {mult} != {expected_mult}"

    print("\n=== Check H-Rn (Z=1..86) fractional or negative magmoms ===")
    anomalies = []
    for z in range(1, 87):
        magmom = float(ground_state_magnetic_moments[z])
        if abs(magmom - round(magmom)) > 1e-6 or magmom < 0:
            anomalies.append((z, Element.from_Z(z).symbol, magmom))
    print(f"Anomalies in Z=1..86: {anomalies}")

    # Check a few main-group and f-block elements
    for sym in ["H", "Li", "Na", "B", "Al", "Si", "W", "Gd"]:
        z = atomic_numbers[sym]
        magmom = float(ground_state_magnetic_moments[z])
        mult = int(round(magmom)) + 1
        el = Element(sym)
        print(
            f"{sym} (Z={z}): magmom={magmom}, mult={mult}, "
            f"block={el.block}, TM={el.is_transition_metal}, Ln={el.is_lanthanoid}"
        )

    print("\nPASS: spike_01_elements")


if __name__ == "__main__":
    main()
