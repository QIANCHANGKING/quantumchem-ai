"""Spike 04: Verify basis_set_exchange coverage check and Gaussian94 genecp block generation."""

import basis_set_exchange as bse
from ase.data import atomic_numbers


def check_coverage(basis_name: str, elements: list[str]) -> tuple[list[str], list[str]]:
    norm = bse.misc.transform_basis_name(basis_name)
    meta = bse.get_metadata()[norm]
    latest = meta["latest_version"]
    supported_z = {int(z) for z in meta["versions"][latest]["elements"]}

    covered = [el for el in elements if atomic_numbers[el] in supported_z]
    missing = [el for el in elements if atomic_numbers[el] not in supported_z]
    return covered, missing


def main() -> None:
    for basis in ["def2-SVP", "def2-TZVP", "6-31G*", "LANL2DZ"]:
        covered, missing = check_coverage(basis, ["H", "C", "Al", "Fe", "Ag", "Au", "Pt", "Gd"])
        print(f"{basis:10s}: covered={covered}, missing={missing}")

    g94_block = bse.get_basis("def2-TZVP", elements=["Al", "Au"], fmt="gaussian94", header=False)
    lines = g94_block.strip().splitlines()
    print(f"\ndef2-TZVP (Al, Au) gaussian94 lines={len(lines)}")
    print("First 8 lines:")
    for line in lines[:8]:
        print(" ", line)
    ecp_idx = [i for i, line in enumerate(lines) if "AU-ECP" in line.upper()]
    print(f"ECP header line indices: {ecp_idx}")
    assert ecp_idx, "Expected AU-ECP block for Au in def2-TZVP"
    idx = ecp_idx[0]
    print("ECP section preview:")
    for line in lines[max(0, idx - 1) : idx + 10]:
        print(" ", line)

    assert "****" in g94_block
    print("\nPASS: spike_04_bse_genecp")


if __name__ == "__main__":
    main()
