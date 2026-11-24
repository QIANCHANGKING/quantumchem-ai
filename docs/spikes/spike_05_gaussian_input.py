"""Spike 05: Verify pymatgen GaussianInput features (nosymm, stable=opt, genecp, Link0)."""

import tempfile
from pathlib import Path

from ase.io import read as ase_read
from pymatgen.core import Molecule
from pymatgen.io.gaussian import GaussianInput


def main() -> None:
    # Al3 has 3*13 = 39 electrons -> neutral doublet (mult=2) is valid
    mol = Molecule(["Al", "Al", "Al"], [(0.0, 0.0, 0.0), (2.5, 0.0, 0.0), (1.25, 2.1, 0.0)])

    gin = GaussianInput(
        mol=mol,
        charge=0,
        spin_multiplicity=2,
        title="Al3 standard opt+freq",
        functional="UPBE1PBE",
        basis_set="def2TZVP",
        route_parameters={
            "opt": "",
            "freq": "",
            "EmpiricalDispersion": "GD3BJ",
            "nosymm": "",
            "scf": "(xqc,maxcycle=500)",
            "stable": "opt",
        },
        link0_parameters={"%nprocshared": "16", "%mem": "32GB", "%chk": "job.chk"},
    )
    gjf_text = gin.to_str(cart_coords=True)
    print("=== Standard GaussianInput ===")
    print(gjf_text)

    assert "%nprocshared=16" in gjf_text
    assert "%mem=32GB" in gjf_text
    assert "nosymm" in gjf_text
    assert "stable=opt" in gjf_text
    assert "scf=(xqc,maxcycle=500)" in gjf_text

    # Test genecp / gen_basis: note GaussianInput sets basis_set='Gen' when gen_basis is given,
    # so we override basis_set = 'GenECP' when an ECP block is present.
    gin_gen = GaussianInput(
        mol=mol,
        charge=0,
        spin_multiplicity=2,
        title="Al3 genecp test",
        functional="UPBE1PBE",
        route_parameters={"opt": "", "nosymm": ""},
        link0_parameters={"%nprocshared": "8", "%mem": "16GB"},
        gen_basis="Al 0\ndef2TZVP\n****\n",
    )
    gin_gen.basis_set = "GenECP"
    gen_text = gin_gen.to_str(cart_coords=True)
    print("=== GenECP GaussianInput ===")
    print(gen_text)
    assert "UPBE1PBE/GenECP" in gen_text
    assert "Al 0" in gen_text

    # Test round-trip with pymatgen and ASE
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "test.gjf"
        p.write_text(gjf_text, encoding="utf-8")
        gin_back = GaussianInput.from_file(p)
        assert gin_back.charge == 0
        assert gin_back.spin_multiplicity == 2
        assert len(gin_back.molecule) == 3
        atoms = ase_read(p)
        assert len(atoms) == 3

    print("PASS: spike_05_gaussian_input")


if __name__ == "__main__":
    main()
